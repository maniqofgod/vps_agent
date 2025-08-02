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
    
    # Bersihkan direktori lama jika ada dan buat yang baru
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
                # Tambahkan query string ke nama file untuk keunikan jika ada
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
                # Jika unduhan gagal, hentikan proses dan lemparkan exception
                raise Exception(f"Failed to download media: {arg}") from e
            finally:
                is_input_arg = False
        else:
            new_command.append(arg)
            is_input_arg = False
            
return new_command, stream_media_dir

class ThumbnailGeneratePayload(BaseModel):
    stream_id: int
    ffmpeg_command: List[str]
    upload_url: str # URL untuk mengunggah thumbnail yang sudah jadi

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
    """Menghentikan proses yang ada dan membersihkan direktorinya."""
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

        # Bersihkan juga direktori media yang terkait
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


def _monitor_process(process: subprocess.Popen, payload: StreamStartPayload, media_dir: str):
    """
    Memantau proses FFmpeg, mengirim callback, dan membersihkan media yang diunduh.
    """
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

    # Bersihkan direktori media yang diunduh
    if os.path.exists(media_dir):
        try:
            shutil.rmtree(media_dir)
            logger.info(f"Berhasil membersihkan direktori media: {media_dir}")
        except Exception as e:
            logger.error(f"Gagal membersihkan direktori media {media_dir}: {e}")


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
        # Unduh semua media dan tulis ulang perintah untuk menggunakan path lokal
        logger.info(f"Memulai pengunduhan media untuk stream {payload.stream_id}...")
        rewritten_command, media_dir = download_media_and_rewrite_command(payload.stream_id, payload.ffmpeg_command)
        logger.info(f"Pengunduhan media selesai. Perintah FFmpeg yang baru: {' '.join(rewritten_command)}")

        # Jalankan perintah FFmpeg yang sudah dimodifikasi sebagai subproses
        process = subprocess.Popen(
            rewritten_command,
            text=True
        )
        running_processes[payload.stream_id] = process
        logger.info(f"Memulai proses FFmpeg untuk stream {payload.stream_id} dengan PID: {process.pid}")

        # Jalankan monitor di thread terpisah agar tidak memblokir
        monitor_thread = threading.Thread(target=_monitor_process, args=(process, payload, media_dir))
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
@router.post("/thumbnail/generate", dependencies=[Depends(verify_api_key)])
async def generate_thumbnail(payload: ThumbnailGeneratePayload, background_tasks: BackgroundTasks):
    """
    Menerima perintah untuk membuat thumbnail, menjalankannya di VPS,
    dan mengunggah hasilnya kembali ke server utama.
    """
    logger.info(f"Menerima permintaan untuk membuat thumbnail untuk stream ID: {payload.stream_id}")
    
    media_dir = None
    try:
        # 1. Unduh media yang diperlukan
        logger.info(f"Memulai pengunduhan media untuk thumbnail stream {payload.stream_id}...")
        rewritten_command, media_dir = download_media_and_rewrite_command(payload.stream_id, payload.ffmpeg_command)
        
        # 2. Tentukan path output lokal untuk thumbnail
        local_thumbnail_path = os.path.join(media_dir, "thumbnail.jpg")
        
        # Ganti placeholder output di perintah dengan path lokal
        final_command = [arg if arg != "%%OUTPUT_PATH%%" else local_thumbnail_path for arg in rewritten_command]
        logger.info(f"Perintah thumbnail final: {' '.join(final_command)}")

        # 3. Jalankan FFmpeg untuk membuat thumbnail
        process = subprocess.run(final_command, capture_output=True, text=True, timeout=60)

        if process.returncode != 0:
            logger.error(f"Gagal membuat thumbnail untuk stream {payload.stream_id}: {process.stderr}")
            raise HTTPException(status_code=500, detail=f"FFmpeg failed for thumbnail: {process.stderr}")

        # 4. Unggah thumbnail kembali ke server utama
        if os.path.exists(local_thumbnail_path):
            logger.info(f"Mengunggah thumbnail dari {local_thumbnail_path} ke {payload.upload_url}")
            with open(local_thumbnail_path, 'rb') as f:
                files = {'thumbnail_file': ('thumbnail.jpg', f, 'image/jpeg')}
                # Gunakan header yang sama untuk otentikasi callback
                headers = {"x-agent-api-key": AGENT_CALLBACK_API_KEY}
                response = requests.post(payload.upload_url, files=files, headers=headers)
                response.raise_for_status()
            logger.info(f"Berhasil mengunggah thumbnail untuk stream {payload.stream_id}")
        else:
            raise HTTPException(status_code=500, detail="Thumbnail file was not created.")

    except Exception as e:
        logger.error(f"Gagal dalam proses pembuatan thumbnail untuk stream {payload.stream_id}: {e}", exc_info=True)
        # Pastikan untuk mengirim HTTPException agar client tahu ada masalah
        if not isinstance(e, HTTPException):
            raise HTTPException(status_code=500, detail=str(e))
        else:
            raise e
    finally:
        # 5. Bersihkan direktori media
        if media_dir and os.path.exists(media_dir):
            shutil.rmtree(media_dir)
            logger.info(f"Membersihkan direktori media thumbnail: {media_dir}")
            
    return {"status": "success", "message": "Thumbnail generated and uploaded successfully."}

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

@router.get("/stats", dependencies=[Depends(verify_api_key)])
async def get_stats():
    """Mengembalikan statistik penggunaan sistem (CPU, RAM, Jaringan)."""
    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        ram_usage = psutil.virtual_memory().percent
        net_io = psutil.net_io_counters()
        
        return {
            "cpu_usage_percent": cpu_usage,
            "ram_usage_percent": ram_usage,
            "network_io": {
                "sent": f"{net_io.bytes_sent / 1e9:.2f} GB",
                "recv": f"{net_io.bytes_recv / 1e9:.2f} GB"
            }
        }
    except Exception as e:
        logger.error(f"Gagal mengambil statistik sistem: {e}")
        raise HTTPException(status_code=500, detail=f"Could not retrieve system stats: {e}")

@router.get("/health")
async def health_check():
    """Endpoint sederhana untuk memeriksa apakah agen berjalan."""
    return {"status": "ok", "running_streams": list(running_processes.keys())}
# --- Endpoint untuk Manajemen Agen ---
manage_router = APIRouter()

def _run_agentctl_command(command: str) -> str:
    """Menjalankan perintah agentctl.sh dan mengembalikan outputnya."""
    try:
        # Pastikan skrip dapat dieksekusi
        script_path = "./agentctl.sh"
        os.chmod(script_path, 0o755)
        
        result = subprocess.run(
            [script_path, command],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            # Jika ada error, kembalikan stderr untuk debugging
            return f"Error executing '{command}':\n{result.stderr}"
        return result.stdout
    except FileNotFoundError:
        return "Error: agentctl.sh not found."
    except subprocess.TimeoutExpired:
        return f"Error: Command '{command}' timed out."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"

@manage_router.get("/logs", dependencies=[Depends(verify_api_key)])
async def get_agent_logs():
    """Mengambil log terbaru dari agen menggunakan 'agentctl.sh logs'."""
    # Perintah logs di pm2 bisa berjalan selamanya, jadi kita butuh pendekatan berbeda.
    # Kita akan menggunakan 'pm2 logs --lines 100' untuk mendapatkan 100 baris terakhir.
    try:
        script_path = "./agentctl.sh"
        os.chmod(script_path, 0o755)
        
        # Menggunakan pm2 langsung untuk mendapatkan sejumlah baris log
@manage_router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_agent():
    """Menghentikan layanan agen menggunakan 'agentctl.sh stop'."""
    return _run_agentctl_command("stop")

@manage_router.post("/restart", dependencies=[Depends(verify_api_key)])
async def restart_agent():
    """Memulai ulang layanan agen menggunakan 'agentctl.sh restart'."""
    return _run_agentctl_command("restart")

@manage_router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_agent_status():
    """Mendapatkan status layanan agen menggunakan 'agentctl.sh status'."""
    return _run_agentctl_command("status")
        result = subprocess.run(
            ["pm2", "logs", "vps-agent", "--lines", "200", "--nostream"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error getting logs:\n{result.stderr}"
        return result.stdout
    except Exception as e:
        return f"An unexpected error occurred while fetching logs: {str(e)}"

app.include_router(manage_router, prefix="/agent/v1/manage")

app.include_router(router, prefix="/agent/v1")

if __name__ == "__main__":
    import uvicorn
    # Jalankan server di 0.0.0.0 agar dapat diakses dari luar container/VPS
    uvicorn.run(app, host="0.0.0.0", port=8002)
