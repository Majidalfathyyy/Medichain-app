# MediChain (front end + back end)

Prototipe proposal *MediChain: Platform Rekam Medis Terintegrasi Berbasis Blockchain* (IEIC 2026, IT Healthcare).
Satu proyek: dasbor web dengan **form login per peran** + API FastAPI + PostgreSQL (off-chain) + smart contract Solidity (on-chain, hanya hash dan metadata). Semua data **sintetis**.

## Struktur
| Path | Isi |
|---|---|
| `app/page.tsx`, `app/globals.css` | Aplikasi Next.js + React, portal peran dan ruang kerja responsif |
| `frontend/` | Antarmuka HTML lama, masih tersedia di endpoint `/app/` |
| `app/main.py` | Endpoint REST, autentikasi, RBAC, header keamanan, penyajian frontend |
| `app/hashing.py` | Hash kanonik SHA-256 (+salt) dan audit log berantai |
| `app/chain.py`, `app/chain_ops.py` | `MockChain`, `Web3Chain` (Sepolia), serta outbox transaksi yang bisa dicoba ulang |
| `app/security.py` | scrypt, JWT, rate limiter |
| `contracts/MediChain.sol` | Smart contract: registerRecord, updateRecord, verifyRecord, grant/revokeAccess, event |
| `scripts/seed.py` | 3 akun staf demo; pasien ditambahkan dari aplikasi |
| `scripts/seed_demo_clinic.py` | Menambah dokter spesialis dan pasien demo sintetis secara idempoten |
| `tests/` | `test_core.py` (logika inti), `test_api.py` (end-to-end) |
| `demo-standalone/index.html` | Simulasi mandiri tanpa backend (cukup buka di browser), cadangan bila server tidak bisa dijalankan |

## Menjalankan (mode mock, tanpa blockchain sungguhan)
```bash
pip install -r requirements.txt
cp .env.example .env                       # CHAIN_MODE=mock; untuk demo set ENABLE_TAMPER_SIM=true
set -a; . ./.env; set +a                   # muat .env ke environment (atau set variabelnya manual)
read -rsp 'Password demo: ' SEED_PASSWORD; export SEED_PASSWORD; printf '\n' # input tidak ditampilkan
alembic upgrade head                       # hanya setelah backup bila DB sudah berisi data
python -m scripts.seed
uvicorn app.main:app --reload
```
Buka **http://localhost:8000/** lalu pilih peran di form login. Docker Compose menyajikan Next.js di port 8000 dan API tetap berada di jaringan internal. Untuk pengembangan lokal, jalankan API di port 8000 dan Next.js dengan `npm ci` lalu `npm run dev` (port 3000). Dokumentasi API lokal: `http://localhost:8000/docs` (hanya non-production). Jika PostgreSQL sudah berisi data, jangan langsung jalankan Alembic; ikuti prosedur backup dan tinjau skema di bagian berikut.
PostgreSQL adalah satu-satunya database aplikasi; SQLite hanya dipakai untuk database tes terisolasi. Compose menyimpan PostgreSQL pada volume persisten `pgdata`. Isi `POSTGRES_PASSWORD` dan `JWT_SECRET` di `.env`. Buat dan verifikasi backup, terapkan Alembic secara eksplisit sesuai bagian migrasi di bawah, baru jalankan `docker compose up --build -d`. Menyalakan container tidak menjalankan migrasi otomatis.

### Migrasi skema PostgreSQL
Alembic mengelola versi skema. Operator menjalankan `alembic upgrade head` secara eksplisit sebelum start API production; di lingkungan lokal jalankan setelah `.env` dimuat dan sebelum `scripts.seed`. Revision awal `20261023_0001` adalah baseline: membuat tabel yang belum ada dan mencatat versi skema. Ia tidak mengubah kolom/tabel yang sudah ada. Untuk database yang sudah berisi data, buat dan verifikasi backup PostgreSQL terlebih dahulu, pastikan `DATABASE_URL` menunjuk ke database yang benar, lalu tinjau nama tabel yang ada sebelum menjalankan migrasi. Jangan menjalankan terhadap DB pengguna tanpa persetujuan pemilik. Jangan gunakan `alembic downgrade` pada baseline; pemulihan dilakukan dengan restore backup yang sudah diverifikasi. Perubahan skema berikutnya harus menjadi revision Alembic baru dan menyertakan operasi downgrade yang ditinjau untuk keamanan data.

Contoh backup dan pemeriksaan versi (atur `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, dan `PGPASSFILE` di environment; jangan taruh password di command line):
```bash
pg_dump --format=custom --file=medichain-pre-migration.dump --dbname="$PGDATABASE"
pg_restore --list medichain-pre-migration.dump
alembic current
alembic upgrade head
alembic current
```
Untuk Compose: jalankan `docker compose up -d db`; backup database Compose default tanpa menampilkan password dengan `docker compose exec -T db pg_dump -U medichain -Fc medichain > medichain-pre-migration.dump`; periksa dump dengan `pg_restore --list medichain-pre-migration.dump`; lalu jalankan `docker compose build api`, `docker compose run --rm api alembic upgrade head`, dan setelah berhasil `docker compose up --build -d`. Simpan dump di tempat aman dan jangan commit ke Git.
Untuk rollback yang menjaga data, hentikan API, pulihkan backup ke database baru/terverifikasi, arahkan `DATABASE_URL` ke hasil restore, lalu mulai API kembali. Jangan menghapus volume PostgreSQL sebagai langkah rollback.

### Menjalankan pemeriksaan
```bash
pip install -r requirements-dev.txt
python -m pytest -p no:cacheprovider tests -q
npm ci
npm exec tsc -- --noEmit
npm run build
```
Tes backend mengarahkan koneksi ke SQLite sementara dan MockChain sementara; tes tidak memakai atau mengubah PostgreSQL yang dikonfigurasi untuk aplikasi.

### Memindahkan database SQLite lama ke PostgreSQL
Skrip migrasi membaca `medichain_dev.db` secara read-only dan menyalin semua tabel yang dikenal aplikasi. Buat salinan cadangan file SQLite terlebih dahulu. Pastikan layanan API berhenti menulis selama migrasi dan PostgreSQL tujuan sudah berjalan:

```powershell
Copy-Item .\medichain_dev.db .\medichain_dev.backup.db
docker compose stop api web
docker compose up -d db
docker compose build api
docker compose run --rm --volume "${PWD}/medichain_dev.db:/migration/medichain_dev.db:ro" api python -m scripts.migrate_sqlite_to_postgres --source /migration/medichain_dev.db --preserve-existing
docker compose up --build -d api web
```

Mode `--preserve-existing` menambahkan baris yang belum ada dan melewati semua konflik tanpa menimpa akun atau data PostgreSQL yang sudah ada. Jika PostgreSQL sudah memiliki audit chain sendiri, audit SQLite diverifikasi lalu dibiarkan utuh di file sumber agar dua rantai audit tidak tercampur. Migrasi mencatat ringkasan sumber ke audit PostgreSQL. Opsi `--merge` tetap tersedia hanya untuk kasus ketika nilai SQLite memang boleh mengganti baris dengan primary key yang sama. Migrasi tidak menghapus file SQLite atau volume PostgreSQL.

## Akun demo dan hak tiap peran
| Peran | Username | Dapat melakukan |
|---|---|---|
| Admin | `admin1` | Kelola pengguna, tagihan, status perawatan, jadwal, tracking perjalanan pasien, audit trail, dan verifikasi integritas |
| Dokter | `dokter1` | Baca rekam yang diizinkan, lengkapi diagnosis dan catatan klinis, lihat ECG dan tagihan; integritas hanya baca |
| Pasien | dibuat admin/auditor | Baca rekam medis, ECG, status perawatan, jadwal, dan tagihan miliknya |
| Auditor | `auditor1` | Kelola pengguna dan kata sandi, tagihan, kontrol akses, verifikasi integritas, dan audit trail |

Jadwal langsung dapat dibuat, diubah, dan dihapus oleh admin/dokter. Pasien mengajukan tanggal melalui permohonan; jadwal diterbitkan setelah dokter dan admin sama-sama menyetujui. Perubahan ACL hanya dapat dilakukan auditor. Saat pasien masuk rawat inap, dokter penanggung jawab dipilih otomatis menurut diagnosis dan spesialisasi, lalu tetap sama sampai pasien keluar. ECG hanya tersedia saat rawat inap atau pemulihan setelah operasi.

Password akun demo = nilai `SEED_PASSWORD` yang dipasang operator sebelum menjalankan seed. Jika tidak diatur, seed membuat password acak yang tidak dicetak; admin perlu mengatur ulang password sebelum akun tersebut dipakai. Peran akun dikenali otomatis dari database setelah autentikasi berhasil.

### Pendaftaran pasien dan persetujuan akun
Tautan **Buat akun pasien** tersedia di halaman login. Pendaftaran publik meminta nama, username, email, tanggal lahir, jenis kelamin, dan kata sandi dua kali. Kata sandi minimal 10 karakter dan harus berisi huruf besar, huruf kecil, serta angka. Backend menormalisasi username/email untuk pemeriksaan duplikasi dan membatasi percobaan pendaftaran per alamat IP.

Pendaftaran hanya membuat akun berperan `pasien` dengan status menunggu persetujuan. Pendaftaran publik tidak menerima pilihan peran dan belum membuat rekam medis atau memberikan token sesi. Pasien tidak dapat masuk atau membaca data sebelum disetujui. OTP tetap dinonaktifkan; endpoint OTP yang sudah ada tetap merespons `410` saat `ENABLE_EMAIL_OTP_REGISTRATION=false`.

Admin/auditor membuka menu **Pengguna**, memeriksa data akun, lalu memilih **Tinjau & aktifkan**. Jika tanggal lahir atau jenis kelamin belum tersedia, petugas dapat melengkapinya lewat **Edit profil** terlebih dahulu. Persetujuan membuat tepat satu rekam awal, menghubungkannya hanya ke akun pasien tersebut, mengaktifkan akun, dan menulis `PatientAccountActivated` ke audit trail. Persetujuan ulang ditolak. Akun Google baru (jika Google Sign-In dikonfigurasi) juga menunggu persetujuan; profilnya dapat dilengkapi petugas sebelum aktivasi.

Google Sign-In merupakan jalur opsional dan terpisah. Backend memverifikasi ID token; akun pasien baru yang dibuat melalui Google tidak mendapat akses sebelum disetujui admin/auditor.

Fitur email dan Google memerlukan kredensial dari administrator sebelum digunakan:

* SMTP/OTP tidak diperlukan saat pendaftaran OTP dinonaktifkan. Jika jalur ini diaktifkan kembali, atur `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, dan `OTP_SECRET` dalam `.env`. Untuk layanan SMTP dengan STARTTLS gunakan port 587; untuk SSL langsung gunakan port 465. Gunakan app password atau kredensial SMTP khusus, bukan kata sandi akun email utama.
* Buat OAuth client bertipe **Web application** di Google Cloud Console, tambahkan origin aplikasi (contoh `http://localhost:3000`), lalu isi `GOOGLE_CLIENT_ID` dan `NEXT_PUBLIC_GOOGLE_CLIENT_ID` dengan client ID yang sama. Ikuti panduan resmi [membuat Google client ID](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid); server juga memverifikasi ID token sebelum membuat sesi. Setelah mengubah nilai, mulai ulang Next.js atau rebuild Docker.
* Tanpa client ID, Google Sign-In tidak ditampilkan. Untuk saat ini pasien dibuat oleh admin/auditor.

Menu **Terapi & pemeriksaan** mencatat alergi, instruksi obat, dan permintaan laboratorium/radiologi. Dokter yang memiliki akses klinis dapat menulis dan memperbarui catatan; pasien, admin, dan auditor hanya membaca sesuai ACL. Data detail tetap di PostgreSQL. Perubahan membuat jejak aktivitas dan sidik jari timeline masuk ke outbox blockchain. Ekspor FHIR lengkap menyertakan AllergyIntolerance, MedicationRequest, dan ServiceRequest.

Untuk menambahkan contoh dokter spesialis dan pasien sintetis ke database dev yang sedang dipakai, jalankan `python -m scripts.seed_demo_clinic`. Script aman dijalankan ulang dan hanya menambahkan akun yang belum ada. Username pasien dan dokter dibuat sederhana dari nama, misalnya `abrar.arrazzaq` atau `bima.setiawan`. Sebelum seed, atur `SEED_PASSWORD` ke password dev yang kuat melalui environment lokal; seed tidak mencetak password. Tanpa nilai itu, akun baru mendapat password acak dan admin perlu mengatur ulang sebelum akun dipakai. Data ini hanya untuk demo lokal, jangan digunakan untuk akun nyata.

## Alur demo untuk presentasi
1. Masuk sebagai **dokter**, ubah catatan, simpan, lihat versi naik jadi v2.
2. Masuk sebagai **admin**, buka Simulasi Tampering, ubah diagnosis, lalu Jalankan verifikasi: status Termodifikasi, hash tidak cocok.
3. Masuk lagi sebagai **dokter**, coba simpan: ditolak (409) karena data tidak cocok dengan hash on-chain.
4. Masuk sebagai **auditor**, buka Audit Trail: semua kejadian tercatat dan rantai log utuh.
5. Masuk sebagai **pasien**: hanya rekam miliknya yang tampil. Upaya membuka rekam lain lewat API ditolak dan tercatat sebagai AccessLogged.
6. Masuk sebagai admin/auditor untuk menambah akun beserta profil, lalu buat tagihan dan tanggal jatuh tempo. Pasien dan dokter hanya dapat melihat tagihan yang menjadi hak aksesnya.

## Menyambungkan ke Ethereum testnet
Langkah deployment lewat Remix dan konfigurasi `.env` tersedia di [SEPOLIA_SETUP.md](SEPOLIA_SETUP.md).
1. Buat akun khusus testnet Sepolia. Jangan gunakan atau membagikan private key akun mainnet.
2. Deploy `contracts/MediChain.sol` ke Sepolia dengan Remix atau Hardhat (compiler Solidity 0.8.20+). Akun deployer otomatis menjadi owner dan writer.
3. Salin `.env.sepolia.example` menjadi `.env`, lalu isi RPC URL, alamat kontrak, private key akun Sepolia, dan rahasia JWT. Jika backend memakai akun berbeda dari deployer, owner harus memanggil `setWriter(backendAddress, true)`.
4. API memeriksa koneksi RPC, chain ID, bytecode kontrak, dan status writer ketika Web3 dipakai. Untuk Sepolia gunakan `CHAIN_ID=11155111`.
5. Jalankan `docker compose build api`, lalu `docker compose run --rm api python -m scripts.anchor_existing_records --dry-run`. Dry run hanya membaca database dan RPC, mengestimasi gas penjangan, memberi cadangan 25%, dan memastikan saldo akun backend cukup; biaya deploy kontrak tidak termasuk.
6. Jika hasil dry run sesuai, jalankan perintah yang sama tanpa `--dry-run` untuk mengantre dan mengirim snapshot terkini. Setelah transaksi selesai, jalankan `docker compose up --build -d`. Web Next.js menerima `API_ORIGIN` sebagai build arg agar proxy `/api` menunjuk ke container API. Halaman Integritas menampilkan jaringan dan tautan transaksi.

ETH testnet hanya untuk pengujian dan tidak setara dengan ETH mainnet. Hash yang ditulis ke blockchain bersifat publik dan tidak dapat dihapus; jangan menulis data identitas, diagnosis, atau ECG mentah ke kontrak. Pastikan semua data demo bersifat sintetis.

## Endpoint
| Metode | Path | Peran |
|---|---|---|
| POST | `/auth/login` | publik (dibatasi laju) |
| GET | `/me` | semua |
| GET/POST | `/records` | baca sesuai izin / dokter |
| GET/PUT | `/records/{id}` | baca sesuai izin / dokter |
| GET | `/records/{id}/ecg?start=&duration=` | baca sesuai izin |
| POST | `/records/{id}/verify` | admin, auditor |
| GET | `/records/{id}/integrity` | baca sesuai izin (tanpa menjalankan verifikasi/audit) |
| GET/POST | `/chain/status`, `/chain/sync` | admin, auditor; status dan retry outbox blockchain |
| GET/POST/PUT/DELETE | `/users` dan `/users/{id}` | admin, auditor; buat, kelola, dan hapus akun serta kata sandi |
| GET/POST/PUT/DELETE | `/invoices` dan `/invoices/{id}` | admin, auditor (kelola); dokter (baca sesuai izin); pasien (baca tagihan sendiri) |
| POST | `/invoices/{id}/payment-proofs` | pasien pemilik tagihan; unggah bukti pembayaran, status menunggu verifikasi |
| GET/POST | `/payment-proofs/{id}` dan `/payment-proofs/{id}/review` | admin; lihat bukti dan setujui/tolak secara manual |
| GET/PUT | `/records/{id}/access[/{role}]` | admin/auditor (baca) / auditor (ubah) |
| GET/PUT | `/care[/{id}]` | semua (baca sesuai izin) / admin dan dokter (ubah) |
| GET/POST/PUT/DELETE | `/appointments` | admin dan dokter; pasien (baca jadwal miliknya) |
| GET/POST | `/appointment-requests` | pasien (buat/baca miliknya); admin dan dokter (tinjau) |
| GET | `/audit`, `/audit/verify` | admin, auditor |
| GET | `/tracking?patient_id={id}` | admin (riwayat aktivitas pasien dan dokter penanggung jawab) |
| GET | `/records/{id}/fhir?scope=summary\|full` | ekspor FHIR Bundle untuk pengguna yang punya akses rekam |
| GET/POST | `/records/{id}/observations` | baca sesuai akses / dokter yang ditugaskan (catat tanda vital) |
| GET | `/records/{id}/alerts` | peringatan alur kerja yang dapat ditinjau tenaga klinis |
| GET | `/records/{id}/timeline` | riwayat aktivitas, fingerprint snapshot, status rantai audit dan anchor |
| POST | `/records/{id}/timeline/anchor` | admin/auditor; jangkar snapshot riwayat ke event blockchain |
| GET/POST/DELETE | `/records/{id}/shares[/{share_id}]` | pasien pemilik rekam; buat tautan/QR, lihat riwayat akses, cabut tautan |
| POST | `/share/access` | publik dengan token bearer terbatas waktu; membuka Bundle yang disetujui pasien |
| POST | `/dev/tamper/{id}` | admin, hanya bila `ENABLE_TAMPER_SIM=true` |

Ekspor menggunakan struktur FHIR R4 Bundle berisi sumber klinis, status perawatan, dan observasi vital bila scope lengkap dipilih. Sidik jari ekspor menghitung konten Bundle sebelum extension bukti ditambahkan; status integritas sumber dan versi chain disertakan sebagai extension MediChain. Token berbagi 256-bit hanya diberikan saat pembuatan, disimpan sebagai SHA-256 di database, ditaruh pada fragmen URL (`#token`) agar tidak terkirim dalam request halaman, kedaluwarsa dalam 10 menit–7 hari, dan dapat dicabut pasien. QR dibuat secara lokal dari dependensi `qrcode`; atur `PUBLIC_APP_URL` untuk host publik. Timeline snapshot di-hash dengan salt rekam yang tidak dibagikan, lalu dicatat sebagai hash 32-byte pada event `AccessLogged`; aktivitas lama bisa dijangkar oleh admin/auditor. Peringatan hanya menandai kelengkapan alur (diagnosis belum diisi, observasi belum dicatat pada episode inap, jadwal terlewat, atau integritas belum valid), bukan diagnosis atau rekomendasi medis.

Alur verifikasi: hitung ulang hash dari PostgreSQL, bandingkan dengan `getRecord` di smart contract, kembalikan `valid` / `modified` / `not_registered`.
Perubahan rekam dan ACL lebih dulu disimpan bersama operasi outbox di database, kemudian dikirim ke chain. Jika RPC gagal, status menjadi pending; admin/auditor dapat melihatnya melalui `/chain/status` dan mencoba ulang lewat `POST /chain/sync` atau tombol Sinkronkan transaksi pada menu Integritas. Hash versi lama yang sudah dikirim ke chain tetap immutable.

Pembayaran QRIS GoPay menggunakan QRIS statis. Pasien mengunggah bukti pembayaran dan tagihan tetap menunggu sampai admin mencocokkan transaksi di GoPay Merchant. Persetujuan admin pada bukti menjadi satu-satunya alur yang menandai tagihan lunas. Sebelum deployment, backup database lalu jalankan `alembic upgrade head`; lihat [panduan QRIS GoPay](PANDUAN_QRIS_GOPAY.md) untuk langkah pasien dan admin.

## Kontrol keamanan
| Ancaman | Kontrol |
|---|---|
| Data DB diubah diam-diam | Hash SHA-256 on-chain; verifikasi terpisah untuk rekam dan ECG |
| Tebak isi rekam dari hash on-chain | Salt acak 128 bit per rekam disimpan off-chain; di chain hanya hash dan pengenal turunan (bukan UUID) |
| "Mencuci" data yang sudah diubah lewat update sah | `PUT` ditolak (409) bila hash lokal tidak cocok dengan on-chain |
| Pencurian kredensial | scrypt (n=2^14), verifikasi waktu-konstan, pesan galat seragam, kunci akun 15 menit setelah 5 gagal, rate limit login |
| Token dicuri / peran dicabut | JWT HS256 berumur 30 menit, `iss`/`exp` wajib; peran dibaca dari DB tiap request |
| Akses tanpa hak | RBAC + ACL per rekam; pasien hanya rekam miliknya; penolakan dicatat (DB dan event `AccessLogged`) |
| Log audit diubah | Log berantai hash (`/audit/verify`); log on-chain sebagai pembanding |
| Pengurasan gas lewat spam akses ditolak | Log on-chain penolakan dibatasi 1 per menit per (user, rekam) |
| Kunci backend bocor | Contract punya `setWriter` dan `setPaused`; kunci hanya akun testnet |
| Injeksi dan input liar | Pydantic dengan batas panjang dan pola; SQLAlchemy ber-parameter |
| Kebocoran konfigurasi | Rahasia hanya dari env; production menolak start tanpa `JWT_SECRET` kuat; `/docs` mati di production |
| Browser/XSS/clickjacking | `nosniff`, `X-Frame-Options`, CSP `default-src 'none'`, `no-store`, HSTS (production), CORS dibatasi |
| Privasi | Data profil disimpan di PostgreSQL; data klinis memakai pengenal pseudonim; salt tidak pernah dikirim ke klien; kontainer non-root; port DB tidak dibuka |

## Batasan yang perlu dinyatakan jujur
- Prototipe, bukan sistem klinis. Belum diaudit pihak ketiga (termasuk smart contract) dan belum ada uji penetrasi.
- Pemegang kunci backend tetap bisa menulis hash baru. Verifikasi membuktikan data DB sama dengan yang dicatat, bukan bahwa pencatat jujur.
- Audit log berantai mendeteksi perubahan di tengah rantai, tetapi tidak mendeteksi pemotongan ekor. Perbaikan lanjutan: jangkarkan hash ujung rantai ke blockchain secara berkala.
- Rate limiter dan lock berada di memori satu proses; multi-instance perlu Redis.
- Komit DB dan transaksi chain tidak atomik. Jika commit gagal setelah chain sukses, ada hash yatim; solusinya pola outbox.
- Skema dibuat otomatis untuk dev; production memerlukan penerapan baseline Alembic oleh operator sebelum API start. ECG demo dibuat sintetis pada 250 Hz dengan gelombang P-QRS-T, variasi interval detak, pergeseran baseline, dan derau ringan. Ini hanya visualisasi simulasi, bukan data alat atau alat bantu diagnosis; ganti dengan segmen MIT-BIH (paket `wfdb`) jika dibutuhkan untuk riset.

- Token JWT disimpan di `sessionStorage` agar sesi bertahan saat halaman dimuat ulang pada tab yang sama; menutup tab mengakhiri sesi browser. Tidak ada logout sisi server (token stateless, berumur 30 menit).
- Pemeriksaan terakhir: 16 tes backend lulus dengan SQLite/MockChain terisolasi; koneksi PostgreSQL dan 26 tabel aplikasi diperiksa dengan query baca saja; pemeriksaan TypeScript dan build Next.js berhasil. Alur tulis aplikasi terhadap PostgreSQL pengguna, build image Docker, pengujian interaktif browser, dan kompilasi/deploy Solidity belum dilakukan. Lakukan hanya pada lingkungan dan data sintetis yang disetujui.
- Purge pasien Versi 1 tersedia sebagai pratinjau melalui `python -m scripts.purge_v1_patients`; gunakan `--execute` hanya setelah `DATABASE_URL` dipastikan menunjuk ke database Versi 1 yang benar. Catatan immutable di blockchain tidak dapat dihapus.
