#!/bin/bash

# Script untuk menginstal dan mengatur StreamCurl VPS Agent
# Dijalankan di server VPS yang bersih (direkomendasikan Ubuntu 22.04)

echo "============================================="
echo "Memulai Instalasi StreamCurl VPS Agent..."
echo "============================================="

# Pastikan skrip berhenti jika terjadi error
set -e

# 1. Perbarui daftar paket dan instal dependensi sistem
echo "[1/4] Menginstal dependensi sistem (git, python3, pip)..."
sudo apt-get update
sudo apt-get install -y git python3 python3-pip

echo "Dependensi sistem berhasil diinstal."
echo "---------------------------------------------"

# 2. Kloning repositori agen dari GitHub
echo "[2/4] Mengkloning repositori agen dari GitHub..."
git clone https://github.com/maniqofgod/vps_agent.git
cd vps_agent

echo "Repositori berhasil dikloning."
echo "---------------------------------------------"

# 3. Instal dependensi Python
echo "[3/4] Menginstal dependensi Python menggunakan pip..."
pip3 install -r requirements.txt

echo "Dependensi Python berhasil diinstal."
echo "---------------------------------------------"

# 4. Selesai! Tampilkan instruksi untuk menjalankan agen
echo "[4/4] Instalasi Selesai!"
echo "============================================="
echo "Untuk menjalankan agen, gunakan perintah berikut:"
echo ""
echo "cd vps_agent"
echo "AGENT_API_KEY=\"GANTI_DENGAN_API_KEY_ANDA\" uvicorn main:app --host 0.0.0.0 --port 8002"
echo ""
echo "PENTING: Ganti 'GANTI_DENGAN_API_KEY_ANDA' dengan kunci API yang sama"
echo "dengan yang Anda konfigurasikan di panel admin StreamCurl untuk VPS ini."
echo "============================================="
