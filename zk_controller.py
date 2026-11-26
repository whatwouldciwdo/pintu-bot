import logging
from zk import ZK

logger = logging.getLogger("zk_controller")

def unlock_door(ip: str, port: int = 4370, delay: int = 5, timeout: int = 5):
    """
    Trigger relay unlock pada perangkat ZKTeco via UDP protokol.
    """
    zk = ZK(ip, port=port, timeout=timeout, password=0, force_udp=True, ommit_ping=False)
    conn = None
    try:
        conn = zk.connect()
        conn.unlock(time=delay)
        logger.info(f"Relay pintu {ip}:{port} berhasil di-trigger selama {delay}s")
        return True, f"Relay pintu aktif selama {delay} detik."
    except Exception as e:
        logger.error(f"Gagal unlock {ip}:{port}: {e}")
        return False, str(e)
    finally:
        if conn:
            try:
                conn.disconnect()
            except:
                pass

def check_status(ip: str, port: int = 4370, timeout: int = 4):
    """
    Cek konektivitas dan informasi perangkat ZKTeco.
    """
    zk = ZK(ip, port=port, timeout=timeout, password=0, force_udp=True, ommit_ping=False)
    conn = None
    try:
        conn = zk.connect()
        sn = conn.get_serialnumber()
        fw = conn.get_firmware_version()
        return True, {"serial": sn, "firmware": fw}
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            try:
                conn.disconnect()
            except:
                pass
