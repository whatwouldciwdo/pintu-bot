# ZKTeco WhatsApp Door Opener (via WAHA)

Aplikasi jembatan untuk mengontrol dan membuka pintu akses **ZKTeco** secara otomatis melalui pesan WhatsApp menggunakan gateway **WAHA (WhatsApp HTTP API)**.

---

## 🏗️ Arsitektur Sistem

```text
[ User / Admin WhatsApp ]
          │ (Kirim: "#buka 1")
          ▼
[ WAHA Gateway ] (http://10.8.140.67:3010)
          │ (Webhook POST /webhook)
          ▼
[ ZKTeco Door Bot Server ] (Port: 3114)
   - Verifikasi nomor Admin (Whitelist)
   - Parse perintah (#buka 1, #buka 2, #status, #menu)
          │
          ▼ (Trigger Remote Unlock via UDP Port 4370)
[ ZKTeco Standalone Device ] (192.168.141.41 / 42)
   - Relay door lock terbuka (5 detik) -> Otomatis mengunci kembali
          │
          ▼ (Kirim konfirmasi via WAHA API)
[ Balasan WhatsApp: "✅ Pintu 1 Berhasil Dibuka!" ]
```

---

## ⚙️ Konfigurasi ([config.json](file:///d:/code/pintu-bot/config.json))

```json
{
  "waha": {
    "api_url": "http://10.8.140.67:3010",
    "session": "pintu",
    "api_key": "WahaCilegon-2026"
  },
  "security": {
    "group_only": true,
    "allowed_groups": [
      "ISI_GROUP_ID_DISINI@g.us"
    ],
    "group_whitelist_enabled": false,
    "whitelist_enabled": true,
    "allowed_numbers": [
      "6287814111808"
    ],
    "require_pin": false,
    "pin": "1234"
  },
  "doors": {
    "server": {
      "name": "CLGDOORSERVER",
      "ip": "192.168.141.41",
      "port": 4370,
      "unlock_delay": 5
    },
    "har": {
      "name": "CLGDOORLT3",
      "ip": "192.168.141.42",
      "port": 4370,
      "unlock_delay": 5
    }
  },
  "server": {
    "host": "0.0.0.0",
    "port": 3114
  }
}
```

### Cara Mendapatkan Group ID (`xxx@g.us`)
1. Masukkan nomor bot WhatsApp ke grup target.
2. Dari salah satu nomor admin yang terdaftar di `allowed_numbers`, ketik **`#groupid`** di dalam grup tersebut — bot akan membalas dengan Group ID-nya.
3. Atau buka endpoint `http://<IP_SERVER>:3114/groups` di browser untuk melihat daftar grup dari WAHA.
4. Salin Group ID (format `120363xxxxxxxx@g.us`) ke `allowed_groups` di `config.json`.

---

## 🐧 Cara Deploy ke Server Ubuntu via Docker

Semua berkas Docker sudah disiapkan ([Dockerfile](file:///d:/open-close-door/Dockerfile) & [docker-compose.yml](file:///d:/open-close-door/docker-compose.yml)).

### 1. Salin Folder Project ke Server Ubuntu
Salin seluruh isi folder `open-close-door` ke server Ubuntu Anda (misal ke `/opt/open-close-door` atau `~/open-close-door`).

### 2. Jalankan Container dengan Docker Compose
Buka terminal server Ubuntu di direktori folder project, lalu jalankan:

```bash
docker compose up -d --build
```

Cek status container:
```bash
docker compose ps
docker compose logs -f
```

Dashboard web akan aktif di:
👉 `http://<IP_SERVER_UBUNTU>:3114`

---

## 🔗 Hubungkan Webhook di WAHA

Di dashboard WAHA Anda (`http://10.8.140.67:3010/dashboard/`):
1. Buka session **`pintu`**
2. Masuk ke tab **Webhooks**
3. Masukkan Webhook URL:
   ```text
   http://<IP_SERVER_UBUNTU>:3114/webhook
   ```
4. Pilih event: `message` atau `message.created` lalu simpan.

---

## 📱 Daftar Perintah WhatsApp (Di Grup Target)

Semua perintah wajib diawali `#` agar percakapan biasa di grup tidak memicu bot.

| Perintah | Deskripsi |
| :--- | :--- |
| **`#command`** | Menampilkan panduan lengkap semua command dari Pintu Bot (`#`) dan FortiGate Bot (`!`) |
| **`#menu`** atau **`#help`** | Menampilkan panduan dan daftar pintu |
| **`#buka server`** atau **`#buka pintu server`** | Membuka Pintu Server (`CLGDOORSERVER`) selama 5 detik lalu mengunci otomatis |
| **`#buka har`** atau **`#buka pintu har`** | Membuka Pintu HAR (`CLGDOORLT3`) selama 5 detik lalu mengunci otomatis |
| **`#status`** | Mengecek konektivitas real-time ke semua mesin ZKTeco |
| **`#groupid`** | Menampilkan Group ID (`xxx@g.us`) dari grup saat ini |
