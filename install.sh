#!/bin/bash

# Script untuk menginstal dan mengatur StreamCurl VPS Agent
# Dijalankan di server VPS yang bersih (direkomendasikan Ubuntu 22.04)

echo "============================================="
echo "Memulai Instalasi StreamCurl VPS Agent..."
echo "============================================="

# Pastikan skrip berhenti jika terjadi error
set -e

# 1. Perbarui daftar paket dan instal dependensi sistem
echo "[1/5] Menginstal dependensi sistem (git, python3, pip)..."
sudo apt-get update
sudo apt-get install -y git python3 python3-pip

echo "Dependensi sistem berhasil diinstal."
echo "---------------------------------------------"

# 2. Kloning repositori agen dari GitHub
echo "[2/5] Mengkloning repositori agen dari GitHub..."
git clone https://github.com/maniqofgod/vps_agent.git
cd vps_agent

echo "Repositori berhasil dikloning."
echo "---------------------------------------------"

# 3. Instal dependensi Python
echo "[3/5] Menginstal dependensi Python menggunakan pip..."
pip3 install -r requirements.txt

echo "Dependensi Python berhasil diinstal."
echo "---------------------------------------------"

# 4. Hasilkan Kunci API secara otomatis
echo "[4/5] Menghasilkan Kunci API unik..."
# Jalankan aplikasi di latar belakang untuk membuat file .env
python3 main.py &
# Simpan PID dari proses latar belakang
PID=$!
# Beri waktu 3 detik untuk aplikasi memulai dan membuat file
sleep 3
# Hentikan proses pembuatan kunci
kill $PID
echo "Kunci API telah dibuat dan disimpan di file .env"
echo "---------------------------------------------"


# 5. Selesai! Tampilkan Kunci API dan instruksi
API_KEY=$(grep AGENT_API_KEY .env | cut -d '=' -f2)

echo "[5/5] Instalasi Selesai!"
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
echo "Untuk menjalankan agen secara manual, gunakan perintah:"
echo "cd vps_agent && uvicorn main:app --host 0.0.0.0 --port 8002"
echo "========================================================================"
