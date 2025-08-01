#!/bin/bash

# Script untuk menginstal dan mengatur StreamCurl VPS Agent
# Dijalankan di server VPS yang bersih (direkomendasikan Ubuntu 22.04)

echo "============================================="
echo "Memulai Instalasi StreamCurl VPS Agent..."
echo "============================================="

# Pastikan skrip berhenti jika terjadi error
set -e

# 1. Perbarui daftar paket dan instal dependensi sistem
echo "[1/6] Menginstal dependensi sistem (git, python3, pip, nodejs, npm)..."
sudo apt-get update
sudo apt-get install -y git python3 python3-pip nodejs npm

echo "Dependensi sistem berhasil diinstal."
echo "---------------------------------------------"

# 2. Instal PM2 Process Manager
echo "[2/6] Menginstal PM2 Process Manager via npm..."
sudo npm install pm2 -g

echo "PM2 berhasil diinstal."
echo "---------------------------------------------"

# 3. Kloning repositori agen dari GitHub
echo "[3/6] Mengkloning repositori agen dari GitHub..."
# Hapus direktori lama jika ada untuk instalasi ulang
rm -rf vps_agent
git clone https://github.com/maniqofgod/vps_agent.git
cd vps_agent

echo "Repositori berhasil dikloning."
echo "---------------------------------------------"

# 4. Instal dependensi Python
echo "[4/6] Menginstal dependensi Python menggunakan pip..."
pip3 install -r requirements.txt

echo "Dependensi Python berhasil diinstal."
echo "---------------------------------------------"

# 5. Hasilkan Kunci API dan mulai layanan dengan PM2
echo "[5/6] Menghasilkan Kunci API dan memulai layanan agen..."
# Panggil fungsi Python secara langsung untuk membuat .env dan API key secara andal
echo "Membuat file .env dan API Key..."
python3 -c "from main import setup_api_key; setup_api_key()"

# Hapus proses lama jika ada untuk memastikan instalasi bersih
pm2 delete vps-agent || true

# Jalankan aplikasi dengan PM2 (sekarang akan membaca .env yang sudah ada)
pm2 start "uvicorn main:app --host 0.0.0.0 --port 8002" --name vps-agent
pm2 save
# Atur PM2 untuk berjalan saat startup (menggunakan path dinamis)
sudo env PATH=$PATH pm2 startup systemd -u $(whoami) --hp $(echo $HOME)

echo "Layanan agen telah dimulai dengan PM2."
echo "---------------------------------------------"

# 6. Selesai! Tampilkan Kunci API dan instruksi
chmod +x agentctl.sh
API_KEY=$(grep AGENT_API_KEY .env | cut -d '=' -f2)

echo "[6/6] Instalasi Selesai!"
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
