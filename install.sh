#!/bin/bash

# Script untuk menginstal atau menginstal ulang StreamCurl VPS Agent
# Dijalankan di server VPS yang bersih (direkomendasikan Ubuntu 22.04)

echo "============================================="
echo "Memulai Instalasi StreamCurl VPS Agent..."
echo "============================================="

# Pastikan skrip berhenti jika terjadi error
set -e

# Langkah 0: Pembersihan Instalasi Sebelumnya
echo "[0/7] Membersihkan instalasi sebelumnya (jika ada)..."
# Hentikan dan hapus proses PM2 yang mungkin sudah ada untuk menghindari konflik
if pm2 list | grep -q "vps-agent"; then
    echo "Layanan 'vps-agent' yang ada ditemukan. Menghentikan dan menghapusnya..."
    pm2 stop vps-agent || true
    pm2 delete vps-agent || true
    pm2 save --force
    echo "Layanan PM2 lama berhasil dihapus."
else
    echo "Tidak ada layanan 'vps-agent' yang berjalan."
fi

# Hapus direktori lama jika ada untuk instalasi ulang yang bersih
if [ -d "vps_agent" ]; then
    echo "Direktori 'vps_agent' lama ditemukan. Menghapusnya..."
    rm -rf vps_agent
    echo "Direktori lama berhasil dihapus."
fi
echo "Pembersihan selesai."
echo "---------------------------------------------"


# 1. Perbarui daftar paket dan instal dependensi sistem
echo "[1/7] Menginstal dependensi sistem (git, python3, pip, venv, ffmpeg)..."
sudo apt-get update
sudo apt-get install -y git python3 python3-pip python3-venv ffmpeg

echo "Dependensi sistem berhasil diinstal."
echo "---------------------------------------------"

# 2. Instal PM2 Process Manager
echo "[2/7] Menginstal PM2 Process Manager via npm..."
sudo npm install pm2 -g

echo "PM2 berhasil diinstal."
echo "---------------------------------------------"

# 3. Kloning repositori agen dari GitHub
echo "[3/7] Mengkloning repositori agen dari GitHub..."
git clone https://github.com/maniqofgod/vps_agent.git
cd vps_agent

echo "Repositori berhasil dikloning."
echo "---------------------------------------------"

# 4. Buat dan aktifkan Virtual Environment
echo "[4/7] Membuat Virtual Environment Python..."
python3 -m venv venv

echo "Virtual Environment berhasil dibuat."
echo "---------------------------------------------"

# 5. Instal dependensi Python di dalam venv
echo "[5/7] Menginstal dependensi Python menggunakan pip di dalam venv..."
source venv/bin/activate
pip install -r requirements.txt
deactivate

echo "Dependensi Python berhasil diinstal."
echo "---------------------------------------------"

# 6. Hasilkan Kunci API dan mulai layanan dengan PM2
echo "[6/7] Menghasilkan Kunci API dan memulai layanan agen..."
# Panggil fungsi Python secara langsung untuk membuat .env dan API key secara andal
echo "Membuat file .env dan API Key..."
venv/bin/python -c "from main import setup_api_key; setup_api_key()"

# Jalankan aplikasi dengan PM2 menggunakan path absolut ke uvicorn di venv
UVICORN_PATH="venv/bin/uvicorn"
PYTHON_PATH="venv/bin/python"
pm2 start "$UVICORN_PATH" --name vps-agent --interpreter "$PYTHON_PATH" -- main:app --host 0.0.0.0 --port 8002
pm2 save
# Atur PM2 untuk berjalan saat startup (menggunakan path dinamis)
sudo env PATH=$PATH pm2 startup systemd -u $(whoami) --hp $(echo $HOME)

echo "Layanan agen telah dimulai dengan PM2."
echo "---------------------------------------------"

# 7. Selesai! Tampilkan Kunci API dan instruksi
chmod +x agentctl.sh
API_KEY=$(grep AGENT_API_KEY .env | cut -d '=' -f2)

echo "[7/7] Instalasi Selesai!"
echo "========================================================================"
echo "                 >>> KUNCI API AGEN VPS ANDA <<<"
echo "========================================================================"
echo ""
echo " $API_KEY"
echo ""
echo "========================================================================"
echo "PENTING: Salin Kunci API di atas dan masukkan ke dalam kolom 'API Key'"
echo "di panel admin StreamCurl saat Anda menambahkan VPS ini."
echo "------------------------------------------------------------------------"
echo "Layanan agen sekarang berjalan di latar belakang dikelola oleh PM2."
echo "Gunakan perintah berikut dari dalam direktori 'vps_agent':"
echo ""
echo "  ./agentctl.sh logs      -> Untuk melihat log"
echo "  ./agentctl.sh stop      -> Untuk menghentikan layanan"
echo "  ./agentctl.sh restart   -> Untuk memulai ulang layanan"
echo "  ./agentctl.sh apikey    -> Untuk melihat API Key lagi"
echo ""
echo "========================================================================"
