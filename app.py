import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

from zk_controller import unlock_door, check_status
from waha_client import WAHAClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("door_server")

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

app = FastAPI(title="ZKTeco WhatsApp Door Opener")

def normalize_phone(phone_str: Any) -> str:
    """Bersihkan format nomor telepon agar seragam (misal: 62812xxx)"""
    if not phone_str:
        return ""
    s = str(phone_str).strip()
    # Buang domain @c.us, @s.whatsapp.net, @lid, @g.us
    if "@" in s:
        s = s.split("@")[0]
    # Buang suffix device multi-device WhatsApp, misal :0, :1, :12
    if ":" in s:
        s = s.split(":")[0]
    cleaned = re.sub(r"[^\d]", "", s)
    if cleaned.startswith("08"):
        cleaned = "628" + cleaned[2:]
    elif cleaned.startswith("8") and 9 <= len(cleaned) <= 13:
        cleaned = "62" + cleaned
    return cleaned

def extract_phone_candidates(sender_id: str, payload: dict = None) -> list[str]:
    """Ekstraksi semua kemungkinan nomor telepon atau JID pengirim dari webhook WAHA."""
    raw_candidates = []
    if sender_id:
        raw_candidates.append(sender_id)
        
    if payload and isinstance(payload, dict):
        # 1. Direct fields di root payload
        for field in ["from", "author", "participant", "chatId", "to"]:
            val = payload.get(field)
            if isinstance(val, str) and val:
                raw_candidates.append(val)
                
        # 2. Objek sender
        sender_obj = payload.get("sender")
        if isinstance(sender_obj, dict):
            for field in ["id", "phone", "pushName", "formattedName"]:
                val = sender_obj.get(field)
                if isinstance(val, str) and val:
                    raw_candidates.append(val)
                    
        # 3. String message ID (seringkali memuat nomor asli: false_628xxx@c.us_...)
        msg_id = payload.get("id")
        if isinstance(msg_id, str):
            raw_candidates.append(msg_id)
            id_matches = re.findall(r"(\d{9,15})@", msg_id)
            raw_candidates.extend(id_matches)

        # 4. Objek _data (struktur internal Baileys/WPP/NOWEB)
        d = payload.get("_data")
        if isinstance(d, dict):
            for field in ["author", "from", "participant", "to"]:
                val = d.get(field)
                if isinstance(val, str) and val:
                    raw_candidates.append(val)
            
            d_id = d.get("id")
            if isinstance(d_id, dict):
                for field in ["remote", "participant", "_serialized"]:
                    val = d_id.get(field)
                    if isinstance(val, str) and val:
                        raw_candidates.append(val)
                        
            d_key = d.get("key")
            if isinstance(d_key, dict):
                for field in ["remoteJid", "participant", "remoteJidPn", "participantPn"]:
                    val = d_key.get(field)
                    if isinstance(val, str) and val:
                        raw_candidates.append(val)
                        
            d_sender = d.get("sender")
            if isinstance(d_sender, dict):
                for field in ["id", "pushName", "verifiedName"]:
                    val = d_sender.get(field)
                    if isinstance(val, str) and val:
                        raw_candidates.append(val)

    cleaned = []
    for c in raw_candidates:
        norm = normalize_phone(c)
        if norm and norm not in cleaned:
            cleaned.append(norm)
            
    return cleaned

def normalize_group_id(group_id: Any) -> str:
    """Normalisasi Group ID WhatsApp agar selalu berakhiran @g.us."""
    if not group_id:
        return ""
    s = str(group_id).strip().lower()
    if not s:
        return ""
    if "@" not in s:
        s = f"{s}@g.us"
    return s

def is_group_chat(chat_id: str) -> bool:
    return isinstance(chat_id, str) and chat_id.strip().lower().endswith("@g.us")

def is_allowed_group(chat_id: str, config: dict) -> bool:
    sec = config.get("security", {})
    allowed_groups = [
        normalize_group_id(g)
        for g in sec.get("allowed_groups", [])
        if str(g).strip()
    ]
    return normalize_group_id(chat_id) in allowed_groups

def extract_participant_id(payload: dict, fallback: str = "") -> str:
    """Ambil ID pengirim asli (anggota grup) dari payload webhook WAHA."""
    if not isinstance(payload, dict):
        return fallback

    for field in ["participant", "author"]:
        val = payload.get(field)
        if isinstance(val, str) and val:
            return val

    d = payload.get("_data")
    if isinstance(d, dict):
        d_key = d.get("key")
        if isinstance(d_key, dict):
            for field in ["participantPn", "participant"]:
                val = d_key.get(field)
                if isinstance(val, str) and val:
                    return val

        for field in ["author", "participant"]:
            val = d.get(field)
            if isinstance(val, str) and val:
                return val

        d_id = d.get("id")
        if isinstance(d_id, dict):
            val = d_id.get("participant")
            if isinstance(val, str) and val:
                return val

    return fallback

def is_authorized(sender_id: str, config: dict, payload: dict = None, in_group: bool = False) -> tuple[bool, str, list[str]]:
    sec = config.get("security", {})
    if in_group:
        if not sec.get("group_whitelist_enabled", False):
            return True, normalize_phone(sender_id), []
    else:
        if not sec.get("whitelist_enabled", False):
            return True, normalize_phone(sender_id), []

    allowed = [normalize_phone(num) for num in sec.get("allowed_numbers", [])]
    candidates = extract_phone_candidates(sender_id, payload)

    primary = candidates[0] if candidates else normalize_phone(sender_id)

    # Cek apakah salah satu kandidat pengirim cocok dengan whitelist
    for cand in candidates:
        if cand in allowed:
            return True, cand, allowed

    return False, primary, allowed

def process_door_command(
    chat_id: str,
    participant_id: str,
    sender_name: str,
    text: str,
    config: dict,
    payload: dict = None,
    message_id: str = None
):
    waha_cfg = config.get("waha", {})
    waha = WAHAClient(
        api_url=waha_cfg.get("api_url", "http://localhost:3000"),
        session=waha_cfg.get("session", "default"),
        api_key=waha_cfg.get("api_key", "")
    )

    clean_text = text.strip()
    lower_text = clean_text.lower()
    doors = config.get("doors", {})
    sec = config.get("security", {})
    in_group = is_group_chat(chat_id)

    # 0. Perintah cek Group ID (hanya di grup)
    if lower_text == "#groupid" and in_group:
        allowed = is_allowed_group(chat_id, config)
        status_label = "✅ Sudah terdaftar di `allowed_groups`" if allowed else "⚠️ Belum terdaftar di `allowed_groups`"
        waha.send_text(
            chat_id,
            f"🆔 *Info Grup WhatsApp*\n\n"
            f"Group ID: `{chat_id}`\n"
            f"Status: {status_label}",
            reply_to=message_id
        )
        return

    # 0b. Perintah #command (Panduan lengkap kedua bot: Pintu Bot + FortiGate Bot)
    if lower_text in ["#command", "#commands"]:
        pin_note = " [PIN]" if sec.get("require_pin") else ""
        door_commands = "\n".join(
            [f"• `#buka {k}{pin_note}` — Buka *{v.get('name')}*" for k, v in doors.items()]
        )
        msg = (
            f"📋 *DAFTAR SEMUA COMMAND GRUP*\n\n"
            f"🚪 *1. PINTU BOT (Awali dengan `#`)*\n"
            f"{door_commands}\n"
            f"• `#status` — Cek status koneksi semua perangkat pintu\n"
            f"• `#menu` / `#help` — Tampilkan daftar pintu & panduan\n"
            f"• `#groupid` — Lihat ID grup WhatsApp ini\n"
            f"• `#command` — Tampilkan daftar semua command bot\n\n"
            f"🛡️ *2. FORTIGATE BOT (Awali dengan `!`)*\n"
            f"• `!menu` / `!help` — Tampilkan menu perintah FortiGate\n"
            f"• `!status` — Cek CPU, RAM, Uptime, Hostname & firmware\n"
            f"• `!active` — Lihat user yang sedang aktif browsing & VPN\n"
            f"• `!users` — Lihat daftar akun lokal terdaftar\n"
            f"• `!adduser <user> <pass> [group]` — Buat akun internet baru\n"
            f"  _Contoh: `!adduser budi 123456 Internet-Access`_\n"
            f"• `!deluser <user>` — Hapus akun lokal dari FortiGate\n"
            f"  _Contoh: `!deluser budi`_\n"
            f"• `!kick <ip/username>` — Putus sesi internet user seketika\n"
            f"  _Contoh: `!kick 192.168.1.50` atau `!kick budi`_\n"
            f"• `!kickvpn <username>` — Putus sesi SSL-VPN user\n"
            f"• `!ping <host>` — Tes ping ke IP atau domain\n"
            f"  _Contoh: `!ping 8.8.8.8`_\n\n"
            f"ℹ️ _Catatan: Command `#` untuk Pintu Bot (semua anggota grup), command `!` untuk FortiGate Bot (khusus nomor admin whitelist)._"
        )
        waha.send_text(chat_id, msg, reply_to=message_id)
        return

    # 1. Perintah Menu / Help (wajib awalan #)
    if lower_text in ["#menu", "#help", "#info"]:
        door_list = "\n".join([f"• `{k}` : *{v.get('name')}*" for k, v in doors.items()])
        pin_note = " [PIN]" if sec.get("require_pin") else ""
        door_commands = "\n".join([f"👉 `#buka {k}{pin_note}` : Buka *{v.get('name')}*" for k, v in doors.items()])
        msg = (
            f"🔐 *SISTEM KONTROL PINTU WHATSAPP*\n\n"
            f"Daftar Pintu:\n{door_list}\n\n"
            f"Perintah Tersedia:\n"
            f"{door_commands}\n"
            f"👉 `#status` : Cek status koneksi ke semua pintu\n"
            f"👉 `#command` : Lihat semua command (Pintu Bot & FortiGate Bot)\n"
            f"👉 `#groupid` : Lihat ID grup ini"
        )
        waha.send_text(chat_id, msg, reply_to=message_id)
        return

    # 2. Perintah Status (wajib awalan #)
    if lower_text == "#status":
        results = []
        for k, v in doors.items():
            ip = v.get("ip")
            port = v.get("port", 4370)
            name = v.get("name")
            ok, info = check_status(ip, port)
            if ok:
                results.append(f"✅ *{name}* ({ip}): Online (SN: {info.get('serial')})")
            else:
                results.append(f"❌ *{name}* ({ip}): Offline ({info})")
        waha.send_text(chat_id, "📡 *STATUS PERANGKAT PINTU:*\n\n" + "\n".join(results), reply_to=message_id)
        return

    # Jika hanya mengetik "#buka" tanpa nama pintu
    if lower_text in ["#buka", "#bukapintu", "#open"]:
        examples = "\n".join([f"👉 `#buka {k}`" for k in doors.keys()])
        door_list = ", ".join(doors.keys())
        waha.send_text(
            chat_id,
            f"⚠️ Silakan tentukan pintu yang ingin dibuka.\n\n"
            f"Contoh perintah:\n"
            f"{examples}\n\n"
            f"Pilihan pintu yang tersedia: {door_list}",
            reply_to=message_id
        )
        return

    # 3. Perintah Buka Pintu (wajib diawali # di awal pesan, misal #buka server / #buka har)
    match = re.match(r"^(?:#buka(?:\s+pintu)?|#bukapintu|#open)\s+([a-z0-9_-]+)(?:\s+(\S+))?$", lower_text)
    if match:
        door_id = match.group(1).lower()
        provided_pin = match.group(2) or ""

        # Cek Whitelist (di grup hanya aktif jika group_whitelist_enabled = true)
        authorized, detected_num, allowed_list = is_authorized(
            participant_id, config, payload, in_group=in_group
        )
        if not authorized:
            all_cands = extract_phone_candidates(participant_id, payload)
            logger.warning(
                f"Akses ditolak untuk {participant_id} ({sender_name}) di {chat_id}. "
                f"Kandidat terdeteksi: {all_cands}, Whitelist config: {allowed_list}"
            )
            waha.send_text(
                chat_id,
                f"⛔ *Akses Ditolak!*\n\n"
                f"Nomor WhatsApp Anda terdeteksi: *{detected_num}*\n"
                f"Nomor ini belum terdaftar di whitelist `config.json`.",
                reply_to=message_id
            )
            return

        # Cek PIN jika diaktifkan
        if sec.get("require_pin", False):
            correct_pin = str(sec.get("pin", ""))
            if provided_pin != correct_pin:
                waha.send_text(chat_id, f"⚠️ *PIN Salah!*\nFormat: `#buka {door_id} <PIN>`", reply_to=message_id)
                return

        # Cek apakah pintu valid di konfigurasi (case-insensitive)
        doors_map = {str(k).lower(): v for k, v in doors.items()}
        if door_id not in doors_map:
            available = ", ".join(doors.keys())
            waha.send_text(
                chat_id,
                f"⚠️ Pintu `{door_id}` tidak ditemukan. Pilihan pintu yang ada: {available}",
                reply_to=message_id
            )
            return

        door_info = doors_map[door_id]
        door_name = door_info.get("name", f"Pintu {door_id}")
        ip = door_info.get("ip")
        port = door_info.get("port", 4370)
        delay = door_info.get("unlock_delay", 5)

        logger.info(f"Membuka {door_name} ({ip}) atas permintaan {sender_name} ({participant_id}) di {chat_id}")

        # Eksekusi remote unlock ke ZKTeco
        success, err_msg = unlock_door(ip, port, delay=delay)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if success:
            reply = (
                f"✅ *PINTU BERHASIL DIBUKA!*\n\n"
                f"📍 Lokasi: *{door_name}*\n"
                f"👤 Operator: *{sender_name}*\n"
                f"⏱ Durasi Buka: *{delay} detik* (otomatis mengunci kembali)\n"
                f"🕒 Waktu: *{timestamp}*"
            )
        else:
            reply = (
                f"❌ *GAGAL MEMBUKA PINTU!*\n\n"
                f"📍 Lokasi: *{door_name}*\n"
                f"⚠️ Error: {err_msg}\n"
                f"Pastikan perangkat menyala dan terhubung ke jaringan."
            )
        waha.send_text(chat_id, reply, reply_to=message_id)
        return

@app.post("/webhook")
async def waha_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint webhook untuk menerima event dari WAHA (WhatsApp HTTP API).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)

    # WAHA format: event bisa 'message' atau 'message.created'
    event = body.get("event")
    payload = body.get("payload", {})

    # Support jika WAHA mengirim data pesan langsung di root
    if not payload and "body" in body:
        payload = body

    # Abaikan jika pesan dikirim dari bot sendiri (fromMe)
    if payload.get("fromMe", False):
        return {"status": "ignored_self"}

    message_text = (payload.get("body", "") or payload.get("text", "")).strip()
    chat_id = payload.get("chatId") or payload.get("from") or ""
    message_id = payload.get("id") if isinstance(payload.get("id"), str) else None

    if not message_text or not chat_id:
        return {"status": "no_text_or_sender"}

    in_group = is_group_chat(chat_id)
    participant_id = extract_participant_id(payload, fallback=chat_id) if in_group else chat_id

    # Ambil nama kontak jika ada
    sender_name = (
        payload.get("_data", {}).get("notifyName") or
        payload.get("pushName") or
        participant_id.split("@")[0]
    )

    config = load_config()
    sec = config.get("security", {})
    group_only = sec.get("group_only", True)

    # Filter mode khusus grup
    if group_only:
        if not in_group:
            logger.info(f"Abaikan pesan pribadi dari {sender_name} ({chat_id}) karena mode group_only aktif.")
            return {"status": "ignored_private_chat"}

        if not is_allowed_group(chat_id, config):
            # Izinkan admin whitelist mengecek Group ID di grup yang belum terdaftar
            if message_text.lower() == "#groupid":
                is_admin, _, _ = is_authorized(participant_id, config, payload, in_group=False)
                if is_admin:
                    logger.info(f"Admin {sender_name} meminta #groupid di grup {chat_id}")
                    background_tasks.add_task(
                        process_door_command, chat_id, participant_id, sender_name, message_text, config, payload, message_id
                    )
                    return {"status": "processing_groupid"}

            logger.info(
                f"Abaikan pesan dari grup yang tidak terdaftar: {chat_id} "
                f"(pengirim: {sender_name}, teks: '{message_text}')"
            )
            return {"status": "ignored_unregistered_group"}

    # Hanya proses pesan yang diawali '#' agar obrolan biasa di grup tidak masuk background task
    if not message_text.startswith("#"):
        return {"status": "ignored_non_command"}

    logger.info(f"Command diterima di {chat_id} dari {sender_name} ({participant_id}): '{message_text}'")

    background_tasks.add_task(
        process_door_command, chat_id, participant_id, sender_name, message_text, config, payload, message_id
    )

    return {"status": "processing"}

@app.get("/groups")
async def list_waha_groups():
    """Tampilkan daftar grup WhatsApp yang diikuti bot melalui WAHA API."""
    config = load_config()
    waha_cfg = config.get("waha", {})
    waha = WAHAClient(
        api_url=waha_cfg.get("api_url", "http://localhost:3000"),
        session=waha_cfg.get("session", "default"),
        api_key=waha_cfg.get("api_key", "")
    )
    groups = waha.get_groups()
    simplified = []
    for g in groups:
        if isinstance(g, dict):
            gid = g.get("id") or g.get("JID") or g.get("jid") or ""
            if isinstance(gid, dict):
                gid = gid.get("_serialized") or gid.get("user") or ""
            name = g.get("subject") or g.get("name") or g.get("Name") or "(Tanpa Nama)"
            simplified.append({"id": gid, "name": name})
    return {"groups": simplified, "allowed_groups": config.get("security", {}).get("allowed_groups", [])}

@app.get("/", response_class=HTMLResponse)
async def index():
    config = load_config()
    sec = config.get("security", {})
    allowed_groups = sec.get("allowed_groups", [])
    groups_display = ", ".join(allowed_groups) if allowed_groups else "(belum diatur)"
    mode_label = "Khusus Grup" if sec.get("group_only", True) else "Semua Chat"

    doors_html = ""
    for k, v in config.get("doors", {}).items():
        doors_html += f"""
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:16px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <strong style="font-size:16px;">Pintu {k}: {v.get('name')}</strong><br>
                    <span style="color:#64748b; font-size:13px;">IP: {v.get('ip')}:{v.get('port', 4370)} | Durasi: {v.get('unlock_delay', 5)}s</span>
                </div>
                <form action="/test-unlock/{k}" method="post" style="margin:0;">
                    <button type="submit" style="background:#2563eb; color:white; border:none; padding:8px 16px; border-radius:6px; font-weight:bold; cursor:pointer;">
                        Buka Pintu
                    </button>
                </form>
            </div>
        </div>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>ZKTeco Door Controller</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f1f5f9; margin: 0; padding: 24px; color: #1e293b; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }}
            h1 {{ font-size: 20px; margin-top: 0; display:flex; align-items:center; gap:8px; }}
            .badge {{ background: #22c55e; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
            .card {{ background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px; margin: 16px 0; border-radius: 4px; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚪 ZKTeco WhatsApp Door Controller <span class="badge">Online</span></h1>
            <div class="card">
                <b>Webhook URL:</b> <code>http://&lt;IP-Komputer-Ini&gt;:3114/webhook</code><br>
                <b>Mode Target:</b> {mode_label}<br>
                <b>Target Group ID:</b> <code>{groups_display}</code><br>
                <a href="/groups" style="color:#2563eb; font-size:13px;">Lihat daftar Group ID dari WAHA (/groups)</a>
            </div>
            <h3>Daftar Pintu</h3>
            {doors_html}
            <div style="font-size:12px; color:#94a3b8; margin-top:20px; text-align:center;">
                WhatsApp HTTP API Gateway &bull; ZKTeco Protocol TCP/IP
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/test-unlock/{door_id}")
async def manual_unlock(door_id: str):
    config = load_config()
    doors = config.get("doors", {})
    if door_id not in doors:
        return JSONResponse({"status": "error", "message": "Door not found"}, status_code=404)
    
    d = doors[door_id]
    ok, msg = unlock_door(d.get("ip"), d.get("port", 4370), delay=d.get("unlock_delay", 5))
    if ok:
        return HTMLResponse(f"<h3>✅ Sukses! Pintu {door_id} ({d.get('name')}) berhasil dibuka selama {d.get('unlock_delay', 5)} detik.</h3><a href='/'>Kembali</a>")
    else:
        return HTMLResponse(f"<h3>❌ Gagal: {msg}</h3><a href='/'>Kembali</a>", status_code=500)

if __name__ == "__main__":
    import uvicorn
    cfg = load_config().get("server", {})
    uvicorn.run("app:app", host=cfg.get("host", "0.0.0.0"), port=cfg.get("port", 3114), reload=True)
