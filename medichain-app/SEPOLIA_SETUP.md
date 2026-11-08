# Panduan beralih dari MockChain ke Sepolia

Panduan ini mengaktifkan salah satu chain pada satu waktu melalui `.env`; kode `MockChain` dan `Web3Chain` sudah tersedia di `app/chain.py`. Jangan mengubah pemilihan implementasi di kode. Setelah mengganti `CHAIN_MODE`, restart backend agar konfigurasi dibaca ulang. Gunakan hanya data sintetis.

MockChain menyimpan ledger lokal (`.mockchain.json`, atau volume `/data/mockchain.json` di Docker). Ledger MockChain dan Sepolia terpisah: transaksi Sepolia tidak tersalin ke MockChain, dan mengganti mode kembali ke `mock` hanya membuka ledger lokal yang sudah ada. Database PostgreSQL tetap menjadi sumber data aplikasi.

Sepolia adalah public testnet. Transaksi dan hash yang dikirim dapat dilihat publik di explorer; akun backend membayar biaya gas dalam Sepolia test ETH. Jangan gunakan private key mainnet, data pasien nyata, atau saldo bernilai nyata.

## 1. Uji MockChain terlebih dahulu

1. Di `.env`, pastikan `CHAIN_MODE=mock`. Jangan isi atau bagikan private key.
2. Jalankan aplikasi seperti biasa (`docker compose up --build` untuk Docker, atau jalankan API lokal sesuai `README.md`).
3. Buat data pasien sintetis, lalu buka menu **Integritas**. Pastikan transaksi tercatat, status menjadi valid, dan tidak ada antrean gagal. Untuk admin/auditor, periksa `/chain/status` dan gunakan sinkronisasi jika ada operasi tertunda.
4. Hentikan proses API sebelum mengganti mode.

Langkah ini tidak membutuhkan deploy kontrak atau ETH.

## 2. Siapkan akun testnet

1. Buat dompet baru khusus Sepolia. Jangan gunakan private key dompet mainnet.
2. Isi test ETH ke alamat deployer dari faucet yang tercantum di https://ethereum.org/developers/docs/networks/.
3. Buat endpoint RPC Sepolia dari provider RPC yang Anda pilih. Endpoint RPC bisa berisi API key, jadi simpan hanya di `.env` lokal.

## 3. Deploy kontrak

1. Buka Remix dan unggah `contracts/MediChain.sol`.
2. Compile dengan Solidity 0.8.20 atau lebih baru.
3. Di Deploy & Run, pilih `Injected Provider - MetaMask` dan pastikan wallet berada di Sepolia (chain ID `11155111`).
4. Deploy tanpa constructor arguments. Salin alamat kontrak hasil deployment.
5. Jika akun backend berbeda dari deployer, panggil `setWriter(backendAddress, true)` dari akun owner di Remix. Kontrak hanya menerima transaksi tulis dari writer.

## 4. Konfigurasi backend

Jangan menimpa `.env` yang berisi konfigurasi lokal. Ubah `CHAIN_MODE=mock` menjadi `CHAIN_MODE=web3`, lalu tambahkan/perbarui variabel berikut pada `.env` yang dipakai Compose:

```dotenv
CHAIN_MODE=web3
CHAIN_ID=11155111
CHAIN_NAME=Sepolia
RPC_URL=https://URL-RPC-SEPOLIA-ANDA
CONTRACT_ADDRESS=0xALAMAT_KONTRAK
CHAIN_PRIVATE_KEY=0xPRIVATE_KEY_AKUN_TESTNET_BACKEND
BLOCK_EXPLORER_TX_BASE=https://sepolia.etherscan.io/tx/
```

`CHAIN_PRIVATE_KEY` harus berasal dari akun testnet khusus dan jangan pernah dimasukkan ke Git atau dibagikan. Gunakan akun yang sama dengan deployer agar langsung menjadi writer, atau lakukan langkah `setWriter` di atas.

## 5. Periksa dahulu sebelum transaksi

1. Pastikan `.env` tidak ter-commit (`.env` sudah masuk `.gitignore`) dan `CHAIN_MODE=web3` menunjuk ke chain ID `11155111`.
2. Buat backup database PostgreSQL dan pastikan bisa dibaca sebelum menjalankan proses import data yang sudah ada. Jangan hapus volume database atau ledger mock.
3. Rebuild/restart stack supaya API membaca `.env`: `docker compose up --build -d`.
4. Jika database sudah berisi rekam dari mode mock, jalankan pemeriksaan biaya tanpa menulis data: `docker compose exec api python -m scripts.anchor_existing_records --dry-run`. Periksa jaringan, jumlah rekam/transaksi, saldo, dan estimasi biaya.
5. Jika kontrak tujuan sudah memuat rekam yang sama, script memeriksa hash dan versi. Ketidaksesuaian akan membatalkan proses; jangan mencoba menimpa atau mengganti key rekam.

## 6. Jalankan dan buktikan transaksi

1. Setelah dry-run lolos dan Anda siap memakai Sepolia, jika perlu daftarkan snapshot data lama dengan `docker compose exec api python -m scripts.anchor_existing_records`. Script mengirim transaksi untuk snapshot aktif, mempertahankan nomor versi DB, dan menambahkan baris audit/outbox. Riwayat sebelum deployment tidak direkonstruksi. Perintah ini menulis transaksi publik dan membutuhkan gas.
2. Untuk database kosong, lewati proses anchor; buat satu pasien sintetis dari UI setelah memastikan backend berjalan di mode web3.
3. API memeriksa koneksi RPC, chain ID, bytecode kontrak, dan izin writer saat operasi chain dijalankan. Buka menu Integritas: jaringan, versi, status hash, dan tautan transaksi Sepolia akan terlihat.
4. Jika transaksi tertunda, buka menu Integritas dan pilih **Sinkronkan transaksi**. Status antrean tersedia di `/chain/status`.
5. Sebelum kembali ke MockChain, hentikan backend dan set `CHAIN_MODE=mock`, lalu restart. Data SQL tetap ada, sementara permintaan chain berikutnya memakai ledger mock; chain publik tidak dihapus.

Kontrak menyimpan hash, key pseudonim turunan, versi, waktu, dan event akses; isi rekam klinis/ECG tetap off-chain. Namun hash dan pola transaksi tetap informasi publik, dan smart contract ini prototipe yang belum diaudit pihak ketiga.
