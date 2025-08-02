from fastapi import FastAPI, APIRouter, Depends, HTTPException, Header, Body, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any
import logging
import os
import subprocess
import threading
import requests
import time
import secrets
from dotenv import load_dotenv, find_dotenv, set_key

# --- Konfigurasi Awal & Pembuatan Kunci API ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_api_key():
    """
    Memeriksa, membuat, dan memuat Kunci API dari file .env.
    Mengembalikan kunci API.
    """
    dotenv_path = find_dotenv()
    if not dotenv_path:
        # Buat file .env jika tidak ada
        dotenv_path = ".env"
        open(dotenv_path, 'a').close()
        logger.info("File .env tidak ditemukan, membuat yang baru.")

    load_dotenv(dotenv_path)
    api_key = os.getenv("AGENT_API_KEY")

    if not api_key:
        # Buat dan simpan kunci API baru jika tidak ada di .env
        logger.info("Kunci API tidak ditemukan di .env, membuat kunci baru...")
        new_key = secrets.token_hex(32)
        set_key(dotenv_path, "AGENT_API_KEY", new_key)
        logger.info(f"Kunci API baru telah dibuat dan disimpan di {dotenv_path}")
        return new_key
    
    logger.info("Kunci API berhasil dimuat dari .env")
    return api_key

# Muat atau buat kunci API saat aplikasi dimulai
AGENT_API_KEY = setup_api_key()

app = FastAPI(
    title="StreamCurl VPS Agent",
    description="Agen ringan untuk menjalankan tugas streaming FFmpeg di VPS.",
    version="0.1.1"
)

router = APIRouter()

# Dictionary untuk melacak proses FFmpeg yang sedang berjalan
running_processes: Dict[int, subprocess.Popen] = {}

# --- Model Pydantic untuk validasi payload ---
class StreamStartPayload(BaseModel):
    stream_id: int
    ffmpeg_command: List[str]
    callback_url: str
    callback_api_key: str

class StreamStopPayload(BaseModel):
    stream_id: int

# --- Dependency untuk Keamanan ---
async def verify_api_key(x_api_key: str = Header(...)):
    """Memverifikasi kunci API yang dikirim di header."""
    if x_api_key != AGENT_API_KEY:
        logger.warning(f"Upaya akses ditolak dengan kunci API yang salah: {x_api_key}")
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

# --- Fungsi Helper ---
def _stop_process(stream_id: int):
    """Menghentikan dan membersihkan proses yang ada."""
    if stream_id in running_processes:
        process = running_processes[stream_id]
        if process.poll() is None:  # Jika proses masih berjalan
            logger.info(f"Menghentikan proses yang ada untuk stream {stream_id} (PID: {process.pid})")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"Proses {stream_id} tidak berhenti, memaksa kill.")
                process.kill()
        del running_processes[stream_id]
        logger.info(f"Proses untuk stream {stream_id} telah dibersihkan.")

def _send_status_update(callback_url: str, api_key: str, stream_id: int, status: str, details: str = ""):
    """Mengirim pembaruan status kembali ke server utama."""
    payload = {"stream_id": stream_id, "status": status, "details": details}
    headers = {"X-Agent-Api-Key": api_key}
    try:
        # Coba beberapa kali jika gagal
        for attempt in range(3):
            try:
                response = requests.post(callback_url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                logger.info(f"Berhasil mengirim status '{status}' untuk stream {stream_id} ke {callback_url}")
                return
            except requests.RequestException as e:
                logger.warning(f"Gagal mengirim status (percobaan {attempt+1}/3): {e}")
                time.sleep(2)
        logger.error(f"Gagal mengirim status '{status}' untuk stream {stream_id} setelah beberapa percobaan.")
    except Exception as e:
        logger.error(f"Terjadi kesalahan tak terduga saat mengirim status: {e}")


def _monitor_process(process: subprocess.Popen, payload: StreamStartPayload):
    """Memantau proses FFmpeg dan mengirim callback saat selesai atau gagal."""
    # Beri waktu FFmpeg untuk memulai
    time.sleep(5)
    
    # Periksa apakah proses dimulai dengan sukses
    if process.poll() is None:
        # Proses berjalan, kirim status LIVE
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "LIVE", "Stream is now live on VPS.")
    else:
        # Proses gagal dimulai
        logger.error(f"FFmpeg untuk stream {payload.stream_id} gagal dimulai dengan kode {process.returncode}. Periksa log agen untuk detail.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Error", f"FFmpeg failed to start on VPS with code {process.returncode}. Check agent logs for details.")
        return

    # Tunggu hingga proses selesai
    process.wait()

    # Proses telah selesai
    if process.returncode == 0:
        logger.info(f"Stream {payload.stream_id} selesai dengan sukses.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Idle", "Stream finished successfully on VPS.")
    else:
        logger.error(f"Stream {payload.stream_id} berhenti dengan error. Kode: {process.returncode}. Periksa log agen untuk detail.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Error", f"FFmpeg exited with code {process.returncode} on VPS. Check agent logs for details.")
    
    # Bersihkan dari daftar proses yang berjalan
    if payload.stream_id in running_processes:
        del running_processes[payload.stream_id]


# --- Endpoint API ---
@router.post("/stream/start", dependencies=[Depends(verify_api_key)])
async def start_stream(payload: StreamStartPayload, background_tasks: BackgroundTasks):
    """
    Menerima perintah FFmpeg dan memulainya di VPS ini.
    """
    logger.info(f"Menerima permintaan untuk memulai stream ID: {payload.stream_id}")
    logger.info(f"Perintah FFmpeg: {' '.join(payload.ffmpeg_command)}")

    # Hentikan proses yang ada untuk stream_id ini jika ada
    _stop_process(payload.stream_id)

    try:
        # Jalankan perintah FFmpeg sebagai subproses
        # stdout dan stderr tidak di-pipe untuk menghindari deadlock. Output akan masuk ke log kontainer.
        process = subprocess.Popen(
            payload.ffmpeg_command,
            text=True
        )
        running_processes[payload.stream_id] = process
        logger.info(f"Memulai proses FFmpeg untuk stream {payload.stream_id} dengan PID: {process.pid}")

        # Jalankan monitor di thread terpisah agar tidak memblokir
        monitor_thread = threading.Thread(target=_monitor_process, args=(process, payload))
        monitor_thread.daemon = True
        monitor_thread.start()

    except Exception as e:
        logger.error(f"Gagal memulai subproses untuk stream {payload.stream_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return {"status": "success", "message": f"Stream {payload.stream_id} is starting on VPS."}

@router.post("/stream/stop", dependencies=[Depends(verify_api_key)])
async def stop_stream(payload: StreamStopPayload):
    """
    Menghentikan proses streaming FFmpeg yang sedang berjalan untuk stream_id tertentu.
    """
    logger.info(f"Menerima permintaan untuk menghentikan stream ID: {payload.stream_id}")

    if payload.stream_id not in running_processes:
        logger.warning(f"Tidak ada stream yang berjalan untuk ID {payload.stream_id}, tidak ada tindakan yang diambil.")
        return {"status": "not_found", "message": f"Stream {payload.stream_id} not found or not running."}

    _stop_process(payload.stream_id)

    return {"status": "success", "message": f"Stop command issued for stream {payload.stream_id}."}

@router.get("/test-streaming", dependencies=[Depends(verify_api_key)])
async def test_streaming():
    """
    Menjalankan tes FFmpeg sederhana dan mengembalikan log output.
    """
    logger.info("Menerima permintaan untuk tes streaming.")
    test_command = [
        "ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=5:size=1280x720:rate=30",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            test_command,
            capture_output=True,
            text=True,
            timeout=20
        )
        
        status = "success" if result.returncode == 0 else "failure"
        log_output = result.stdout + "\n" + result.stderr
        
        if status == "success":
            logger.info("Tes streaming FFmpeg berhasil.")
        else:
            logger.error(f"Tes streaming FFmpeg gagal. Kode: {result.returncode}")
            
        return {
            "status": status,
            "return_code": result.returncode,
            "logs": log_output
        }

    except FileNotFoundError:
        logger.error("Perintah FFmpeg tidak ditemukan.")
        raise HTTPException(status_code=500, detail="FFmpeg command not found. Is FFmpeg installed and in the system's PATH?")
    except subprocess.TimeoutExpired:
        logger.error("Tes streaming FFmpeg timeout.")
        raise HTTPException(status_code=500, detail="FFmpeg test command timed out after 20 seconds.")
    except Exception as e:
        logger.error(f"Terjadi kesalahan tak terduga saat tes streaming: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during the test: {str(e)}")

@router.get("/health")
async def health_check():
    """Endpoint sederhana untuk memeriksa apakah agen berjalan."""
    return {"status": "ok", "running_streams": list(running_processes.keys())}

app.include_router(router, prefix="/agent/v1")

if __name__ == "__main__":
    import uvicorn
    # Jalankan server di 0.0.0.0 agar dapat diakses dari luar container/VPS
    uvicorn.run(app, host="0.0.0.0", port=8002)
