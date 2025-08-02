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
import psutil
from dotenv import load_dotenv, find_dotenv, set_key
import shutil
from urllib.parse import urlparse

# --- Direktori untuk media yang diunduh ---
MEDIA_DOWNLOAD_DIR = "/tmp/stream_media"


def download_media_and_rewrite_command(stream_id: int, command: List[str]) -> (List[str], str):
    """
    Mengunduh semua input media dari URL, menyimpannya secara lokal,
    dan menulis ulang perintah FFmpeg untuk menggunakan file lokal.

    Mengembalikan tuple berisi (perintah_baru, direktori_media_lokal).
    """
    stream_media_dir = os.path.join(MEDIA_DOWNLOAD_DIR, str(stream_id))
    
    if os.path.exists(stream_media_dir):
        shutil.rmtree(stream_media_dir)
    os.makedirs(stream_media_dir, exist_ok=True)
    
    logger.info(f"Direktori media untuk stream {stream_id} dibuat di: {stream_media_dir}")

    new_command = []
    is_input_arg = False

    for i, arg in enumerate(command):
        if arg == '-i':
            is_input_arg = True
            new_command.append(arg)
            continue

        if is_input_arg and (arg.startswith('http://') or arg.startswith('https://')):
            try:
                url = arg
                filename = os.path.basename(urlparse(url).path)
                query = urlparse(url).query
                if query:
                    filename += f"_{query}"

                local_path = os.path.join(stream_media_dir, filename)
                
                logger.info(f"Mengunduh media dari {url} ke {local_path}...")
                
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    with open(local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                
                logger.info(f"Berhasil mengunduh {url}")
                new_command.append(local_path)

            except requests.RequestException as e:
                logger.error(f"Gagal mengunduh media dari {arg}: {e}")
                raise Exception(f"Failed to download media: {arg}") from e
            finally:
                is_input_arg = False
        else:
            new_command.append(arg)
            is_input_arg = False
            
    return new_command, stream_media_dir

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
        dotenv_path = ".env"
        open(dotenv_path, 'a').close()
        logger.info("File .env tidak ditemukan, membuat yang baru.")

    load_dotenv(dotenv_path)
    api_key = os.getenv("AGENT_API_KEY")

    if not api_key:
        logger.info("Kunci API tidak ditemukan di .env, membuat kunci baru...")
        new_key = secrets.token_hex(32)
        set_key(dotenv_path, "AGENT_API_KEY", new_key)
        logger.info(f"Kunci API baru telah dibuat dan disimpan di {dotenv_path}")
        return new_key
    
    logger.info("Kunci API berhasil dimuat dari .env")
    return api_key

AGENT_API_KEY = setup_api_key()

app = FastAPI(
    title="StreamCurl VPS Agent",
    description="Agen ringan untuk menjalankan tugas streaming FFmpeg di VPS.",
    version="0.1.1"
)

router = APIRouter()
manage_router = APIRouter()

running_processes: Dict[int, subprocess.Popen] = {}

# --- Model Pydantic ---
class StreamStartPayload(BaseModel):
    stream_id: int
    ffmpeg_command: List[str]
    callback_url: str
    callback_api_key: str

class StreamStopPayload(BaseModel):
    stream_id: int

class ThumbnailGeneratePayload(BaseModel):
    stream_id: int
    ffmpeg_command: List[str]
    upload_url: str
    callback_api_key: str

# --- Dependency Keamanan ---
async def verify_api_key(x_api_key: str = Header(..., alias="x-api-key")):
    if x_api_key != AGENT_API_KEY:
        logger.warning(f"Upaya akses ditolak dengan kunci API yang salah: {x_api_key}")
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

# --- Fungsi Helper ---
def _stop_process(stream_id: int):
    """Menghentikan proses yang ada dan membersihkan direktorinya."""
    if stream_id in running_processes:
        process = running_processes[stream_id]
        if process.poll() is None:
            logger.info(f"Menghentikan proses yang ada untuk stream {stream_id} (PID: {process.pid})")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"Proses {stream_id} tidak berhenti, memaksa kill.")
                process.kill()
        del running_processes[stream_id]
        logger.info(f"Proses untuk stream {stream_id} telah dibersihkan.")

        media_dir = os.path.join(MEDIA_DOWNLOAD_DIR, str(stream_id))
        if os.path.exists(media_dir):
            try:
                shutil.rmtree(media_dir)
                logger.info(f"Berhasil membersihkan direktori media saat stop: {media_dir}")
            except Exception as e:
                logger.error(f"Gagal membersihkan direktori media {media_dir} saat stop: {e}")

def _send_status_update(callback_url: str, api_key: str, stream_id: int, status: str, details: str = ""):
    """Mengirim pembaruan status kembali ke server utama."""
    payload = {"stream_id": stream_id, "status": status, "details": details}
    headers = {"x-agent-api-key": api_key}
    try:
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

def _monitor_process(process: subprocess.Popen, payload: StreamStartPayload, media_dir: str):
    """Memantau proses FFmpeg, mengirim callback, dan membersihkan media yang diunduh."""
    time.sleep(5)
    
    if process.poll() is None:
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "LIVE", "Stream is now live on VPS.")
    else:
        logger.error(f"FFmpeg untuk stream {payload.stream_id} gagal dimulai dengan kode {process.returncode}.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Error", f"FFmpeg failed to start on VPS with code {process.returncode}.")
        return

    process.wait()

    if process.returncode == 0:
        logger.info(f"Stream {payload.stream_id} selesai dengan sukses.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Idle", "Stream finished successfully on VPS.")
    else:
        logger.error(f"Stream {payload.stream_id} berhenti dengan error. Kode: {process.returncode}.")
        _send_status_update(payload.callback_url, payload.callback_api_key, payload.stream_id, "Error", f"FFmpeg exited with code {process.returncode} on VPS.")
    
    if payload.stream_id in running_processes:
        del running_processes[payload.stream_id]

    if os.path.exists(media_dir):
        try:
            shutil.rmtree(media_dir)
            logger.info(f"Berhasil membersihkan direktori media: {media_dir}")
        except Exception as e:
            logger.error(f"Gagal membersihkan direktori media {media_dir}: {e}")

# --- Endpoint API ---
@router.post("/stream/start", dependencies=[Depends(verify_api_key)])
async def start_stream(payload: StreamStartPayload, background_tasks: BackgroundTasks):
    """Menerima perintah FFmpeg dan memulainya di VPS ini."""
    logger.info(f"Menerima permintaan untuk memulai stream ID: {payload.stream_id}")
    _stop_process(payload.stream_id)

    try:
        logger.info(f"Memulai pengunduhan media untuk stream {payload.stream_id}...")
        rewritten_command, media_dir = download_media_and_rewrite_command(payload.stream_id, payload.ffmpeg_command)
        logger.info(f"Pengunduhan media selesai. Perintah FFmpeg yang baru: {' '.join(rewritten_command)}")

        process = subprocess.Popen(rewritten_command, text=True)
        running_processes[payload.stream_id] = process
        logger.info(f"Memulai proses FFmpeg untuk stream {payload.stream_id} dengan PID: {process.pid}")

        monitor_thread = threading.Thread(target=_monitor_process, args=(process, payload, media_dir))
        monitor_thread.daemon = True
        monitor_thread.start()

    except Exception as e:
        logger.error(f"Gagal memulai subproses untuk stream {payload.stream_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return {"status": "success", "message": f"Stream {payload.stream_id} is starting on VPS."}

@router.post("/stream/stop", dependencies=[Depends(verify_api_key)])
async def stop_stream(payload: StreamStopPayload):
    """Menghentikan proses streaming FFmpeg yang sedang berjalan."""
    logger.info(f"Menerima permintaan untuk menghentikan stream ID: {payload.stream_id}")
    if payload.stream_id not in running_processes:
        return {"status": "not_found", "message": f"Stream {payload.stream_id} not found or not running."}
    _stop_process(payload.stream_id)
    return {"status": "success", "message": f"Stop command issued for stream {payload.stream_id}."}

@router.post("/thumbnail/generate", dependencies=[Depends(verify_api_key)])
async def generate_thumbnail(payload: ThumbnailGeneratePayload):
    """Menerima perintah untuk membuat thumbnail, menjalankannya, dan mengunggah hasilnya."""
    logger.info(f"Menerima permintaan thumbnail untuk stream ID: {payload.stream_id}")
    media_dir = None
    try:
        rewritten_command, media_dir = download_media_and_rewrite_command(payload.stream_id, payload.ffmpeg_command)
        local_thumbnail_path = os.path.join(media_dir, "thumbnail.jpg")
        final_command = [arg if arg != "%%OUTPUT_PATH%%" else local_thumbnail_path for arg in rewritten_command]
        
        process = subprocess.run(final_command, capture_output=True, text=True, timeout=60)
        if process.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg failed for thumbnail: {process.stderr}")

        if os.path.exists(local_thumbnail_path):
            with open(local_thumbnail_path, 'rb') as f:
                files = {'thumbnail_file': ('thumbnail.jpg', f, 'image/jpeg')}
                headers = {"x-agent-api-key": payload.callback_api_key}
                response = requests.post(payload.upload_url, files=files, headers=headers)
                response.raise_for_status()
            logger.info(f"Berhasil mengunggah thumbnail untuk stream {payload.stream_id}")
        else:
            raise HTTPException(status_code=500, detail="Thumbnail file was not created.")
    except Exception as e:
        logger.error(f"Gagal dalam proses pembuatan thumbnail: {e}", exc_info=True)
        if not isinstance(e, HTTPException):
            raise HTTPException(status_code=500, detail=str(e))
        raise e
    finally:
        if media_dir and os.path.exists(media_dir):
            shutil.rmtree(media_dir)
    return {"status": "success", "message": "Thumbnail generated and uploaded."}

@router.get("/stats", dependencies=[Depends(verify_api_key)])
async def get_stats():
    """Mengembalikan statistik penggunaan sistem."""
    return {
        "cpu_usage_percent": psutil.cpu_percent(interval=1),
        "ram_usage_percent": psutil.virtual_memory().percent,
    }

@router.get("/health")
async def health_check():
    """Endpoint sederhana untuk memeriksa apakah agen berjalan."""
    return {"status": "ok", "running_streams": list(running_processes.keys())}

# --- Endpoint Manajemen Agen ---
def _run_agentctl_command(command: str) -> str:
    """Menjalankan perintah agentctl.sh dan mengembalikan outputnya."""
    try:
        script_path = "./agentctl.sh"
        os.chmod(script_path, 0o755)
        result = subprocess.run([script_path, command], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error executing '{command}':\n{result.stderr}"
        return result.stdout
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"

@manage_router.get("/logs", dependencies=[Depends(verify_api_key)])
async def get_agent_logs():
    """Mengambil 200 baris log terakhir dari agen."""
    try:
        result = subprocess.run(["pm2", "logs", "vps-agent", "--lines", "200", "--nostream"], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error getting logs:\n{result.stderr}"
        return result.stdout
    except Exception as e:
        return f"An unexpected error occurred while fetching logs: {str(e)}"

@manage_router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_agent():
    """Menghentikan layanan agen."""
    return _run_agentctl_command("stop")

@manage_router.post("/restart", dependencies=[Depends(verify_api_key)])
async def restart_agent():
    """Memulai ulang layanan agen."""
    return _run_agentctl_command("restart")

@manage_router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_agent_status():
    """Mendapatkan status layanan agen."""
    return _run_agentctl_command("status")

app.include_router(router, prefix="/agent/v1")
app.include_router(manage_router, prefix="/agent/v1/manage")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
