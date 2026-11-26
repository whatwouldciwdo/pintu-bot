from zk import ZK

def test_device(ip, port=4370):
    print(f"\n==========================================")
    print(f"Menguji koneksi ke ZKTeco di {ip}:{port}")
    print(f"==========================================")

    # Coba via UDP dulu (default ZKTeco standalone)
    for force_udp in [True, False]:
        protocol_name = "UDP" if force_udp else "TCP"
        print(f"\n[INFO] Mencoba protokol {protocol_name}...")
        zk = ZK(ip, port=port, timeout=5, password=0, force_udp=force_udp, ommit_ping=False)
        conn = None
        try:
            conn = zk.connect()
            print(f"[SUKSES] Terhubung ke {ip} menggunakan {protocol_name}!")
            
            # Cek info device
            firmware = conn.get_firmware_version()
            serial = conn.get_serialnumber()
            device_name = conn.get_device_name()
            print(f"  - Device Name : {device_name}")
            print(f"  - Serial Number: {serial}")
            print(f"  - Firmware     : {firmware}")
            
            # Jangan langsung unlock di test awal, cukup pastikan terhubung dulu
            print(f"[INFO] Perangkat siap untuk kontrol relay (unlock)!")
            return True, protocol_name
        except Exception as e:
            print(f"[GAGAL] Koneksi via {protocol_name} gagal: {e}")
        finally:
            if conn:
                try:
                    conn.disconnect()
                except:
                    pass
    return False, None

if __name__ == "__main__":
    devices = ["192.168.141.41", "192.168.141.42"]
    for ip in devices:
        test_device(ip)
