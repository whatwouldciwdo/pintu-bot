import sys
from zk import ZK

def test_unlock(ip="192.168.141.41", delay=5, port=4370):
    print(f"[+] Menghubungkan ke ZKTeco ({ip}:{port})...")
    zk = ZK(ip, port=port, timeout=5, password=0, force_udp=True, ommit_ping=False)
    conn = None
    try:
        conn = zk.connect()
        print(f"[+] Berhasil terhubung!")
        print(f"[+] Mengirim perintah BUKA PINTU (durasi relay: {delay} detik)...")
        conn.unlock(time=delay)
        print(f"[SUKSES] Relay pintu telah ditrigger aktif!")
        print(f"         Periksa apakah magnetic lock / dropbolt di pintu sudah terbuka.")
    except Exception as e:
        print(f"[ERROR] Gagal membuka pintu: {e}")
    finally:
        if conn:
            try:
                conn.disconnect()
                print(f"[+] Koneksi ditutup.")
            except:
                pass

if __name__ == "__main__":
    target_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.141.41"
    target_delay = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    test_unlock(target_ip, target_delay)
