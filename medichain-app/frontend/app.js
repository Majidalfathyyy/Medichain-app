(() => {
'use strict';
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ROLES = {
  admin:   {n: 'Admin'},
  dokter:  {n: 'Dokter'},
  pasien:  {n: 'Pasien'},
  auditor: {n: 'Auditor'}};
const P = {dash:'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', rm:'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6', ecg:'M3 12h4l3-8 4 16 3-8h4', int:'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5', acl:'M6 11V8a6 6 0 0 1 12 0v3M5 11h14v10H5z', aud:'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1', tmp:'M12 3l10 18H2zM12 10v5M12 18h.01', out:'M9 21H5V3h4M16 17l5-5-5-5M21 12H9', admin:'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', dokter:'M12 5v14M5 12h14', pasien:'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21a8 8 0 0 1 16 0', auditor:'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M21 21l-5-5', db:'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3', hash:'M5 9h14M5 15h14M10 3L8 21M16 3l-2 18', ok:'M5 12l4.5 4.5L19 7', warn:'M12 8v5M12 16.5h.01M12 3l10 18H2z'};
P.users = 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M20 8v6M23 11h-6';
P.bill = 'M4 3h16v18l-4-2-4 2-4-2-4 2zM8 8h8M8 12h8M8 16h4';
const ic = (n) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="${P[n]}"/></svg>`;
const LOGO = '<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 2l12 7v14l-12 7L4 23V9z" fill="currentColor" opacity=".18" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M16 10v12M10 16h12" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>';
const PULSE = '<svg class="pulse" viewBox="0 0 600 70" preserveAspectRatio="none" aria-hidden="true"><path pathLength="100" d="M0 40H90L104 40 116 22 128 40H170L182 46 196 6 210 66 224 40H300L314 34 330 40H400L412 40 424 24 436 40H480L492 46 506 8 520 64 534 40H600"/></svg>';
const VIEWS = {dash: 'Ringkasan', rm: 'Rekam Medis', ecg: 'Visualisasi ECG', int: 'Cek Integritas', tracking: 'Tracking Pasien', acl: 'Kontrol Akses', aud: 'Audit Trail', tmp: 'Simulasi Tampering', users: 'Kelola Pengguna', invoices: 'Tagihan', profile: 'Profil Saya'};
const NAV = {admin: ['dash','rm','ecg','int','tracking','users','invoices','acl','aud','tmp','profile'], dokter: ['dash','rm','ecg','int','invoices','profile'], pasien: ['dash','rm','ecg','int','invoices','profile'], auditor: ['dash','rm','ecg','int','users','invoices','acl','aud','profile']};
const SESSION_KEY = 'medichain.legacy.session';
function readSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    if (!saved || typeof saved.token !== 'string') return null;
    return saved;
  } catch (_) { return null; }
}
const savedSession = readSession();
const S = {token: savedSession?.token || null, role: null, user: null, err: '', restoreError: '', view: savedSession?.view || 'dash', records: [], sel: savedSession?.sel || null, detail: null, ecg: null, st: {}, acl: {}, audit: [], activities: [], chainOk: null, users: [], invoices: [], editUser: null, editInvoice: null, win: {s: 0, d: 5}, booting: !!savedSession?.token};
function saveSession() {
  try {
    if (S.token) sessionStorage.setItem(SESSION_KEY, JSON.stringify({token: S.token, view: S.view, sel: S.sel}));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch (_) { /* storage mungkin dinonaktifkan oleh browser */ }
}

async function api(path, opt = {}) {
  const headers = {};
  if (S.token) headers.Authorization = 'Bearer ' + S.token;
  if (opt.body) headers['Content-Type'] = 'application/json';
  const r = await fetch(path, {method: opt.method || 'GET', headers, body: opt.body ? JSON.stringify(opt.body) : undefined});
  let data = null;
  try { data = await r.json(); } catch (_) { /* tanpa isi */ }
  if (r.status === 401 && S.token) { logout('Sesi berakhir. Silakan masuk lagi.'); throw Object.assign(new Error('Sesi berakhir'), {status: 401, handled: true}); }
  if (!r.ok) throw Object.assign(new Error(data && typeof data.detail === 'string' ? data.detail : 'Permintaan gagal (' + r.status + ')'), {status: r.status});
  return data;
}
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 3500); }
const fail = (e) => { if (!e.handled) toast(e.message); };
const badge = (id) => { const s = S.st[id]; return !s ? '<span class="b n">Belum diverifikasi</span>' : s.status === 'valid' ? '<span class="b ok">✓ Valid</span>' : s.status === 'modified' ? '<span class="b bad">⚠ Termodifikasi</span>' : '<span class="b bad">Belum terdaftar</span>'; };
const cur = () => S.records.find((r) => r.id === S.sel);

// ---------- tampilan ----------
function loginView() {
  return `<div class="lg"><section class="hero"><div class="bn">${LOGO}MediChain</div>
  <h1>Rekam medis yang<br>terbukti utuh.</h1>
  <p>Satu platform untuk rekam medis yang lebih tepercaya. Data klinis tersimpan privat di PostgreSQL, sementara sidik jari SHA-256 di blockchain membuat integritasnya dapat diverifikasi kapan saja.</p>
  ${PULSE}
  <ul class="feat"><li>${ic('db')}Data lengkap di PostgreSQL, hanya pengenal pseudonim</li><li>${ic('hash')}Hash SHA-256 + salt tercatat di smart contract</li><li>${ic('acl')}Akses per peran dan audit trail berantai hash</li></ul>
  <div class="blocks" aria-hidden="true"><span>Blok #1024 · 0x9f3a…c21</span><i></i><span>Blok #1025 · 0x4be1…7d0</span><i></i><span>Blok #1026 · 0xa72c…e58</span></div></section>
  <main class="lside"><div class="lbox"><h2>Masuk ke MediChain</h2><p class="sub">Gunakan username dan password akun Anda.</p>
  <div class="card">
  <form id="lf">
    <label for="u">Username</label><input id="u" name="username" autocomplete="username" required minlength="3" maxlength="40">
    <label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required minlength="8" maxlength="128">
    ${S.err ? `<p class="err" role="alert">${esc(S.err)}</p>` : ''}
    <button class="btn wide" type="submit">Masuk</button>
  </form></div>
  <p class="hint">Prototipe dengan data sintetis. Bukan sistem klinis.</p></div></main></div>`;
}
function picker() {
  const rows = S.view === 'ecg' ? S.records.filter((r) => r.ecg_available) : S.records;
  if (!rows.length) return '';
  return `<div class="row"><label for="ps">Pasien</label><select id="ps" data-action="pick">${rows.map((r) => `<option value="${esc(r.id)}"${r.id === S.sel ? ' selected' : ''}>${esc(r.patient_name || r.pseudo_id)}</option>`).join('')}</select>${badge(S.sel)}</div>`;
}
const head = (t, s) => `<h2>${t}</h2><p class="sub">${s}</p>`;
const empty = () => `<div class="card">Belum ada rekam yang dapat Anda akses.</div>`;

function dashView() {
  const v = S.records.map((r) => S.st[r.id]).filter(Boolean);
  const nOk = v.filter((x) => x.status === 'valid').length, nBad = v.filter((x) => x.status !== 'valid').length;
  const card = (c, i, n, t) => `<div class="st ${c}">${ic(i)}<div><b>${n}</b><span>${t}</span></div></div>`;
  const task = S.role === 'pasien' ? 'Pantau rekam medis, hasil integritas, ECG, dan tagihan Anda.' : S.role === 'dokter' ? 'Tinjau rekam medis, lanjutkan diagnosis, dan lihat tagihan pasien.' : 'Kelola akun, tagihan, hak akses, serta verifikasi integritas data.';
  return `<div class="banner"><h2>Halo, ${esc(S.user.username)}</h2><p>Anda masuk sebagai ${esc(ROLES[S.role].n)}. ${esc(task)}</p>${PULSE}</div>
  <div class="stats">${card('', 'rm', S.records.length, 'Rekam dapat diakses')}${card('ok', 'int', nOk, 'Terverifikasi valid')}${card('bad', 'tmp', nBad, 'Termodifikasi / belum terdaftar')}${card('', 'hash', S.records.length - v.length, 'Belum diverifikasi')}</div>
  <div class="card"><h3>Alur integritas data</h3><div class="flow"><div>${ic('db')}<b>PostgreSQL</b>Data klinis off-chain</div><i>→</i><div>${ic('hash')}<b>SHA-256 + salt</b>Sidik jari data</div><i>→</i><div>${ic('aud')}<b>Smart contract</b>Hash on-chain</div></div>
  <div class="row">${['admin','auditor'].includes(S.role) ? `<button class="btn" data-action="verifyAll">${ic('int')}Verifikasi semua rekam</button>` : ''}<button class="btn alt" data-action="go" data-v="rm">Buka rekam medis</button></div></div>`;
}
function rmView() {
  const d = S.detail, selected = S.records.find((r) => r.id === S.sel), w = S.role === 'dokter' && selected && selected.can_edit;
  const list = `<div class="patient-search"><label for="patient-search">Cari pasien</label><input id="patient-search" type="search" placeholder="Cari nama atau identitas pasien" autocomplete="off"></div>
    <div class="card tw"><table id="patient-table"><thead><tr><th>Nama pasien</th><th>Umur</th><th>Jenis kelamin</th><th>Integritas</th></tr></thead><tbody>${S.records.map((r) => `<tr class="patient-row${r.id === S.sel ? ' selected' : ''}" data-action="pick" data-id="${esc(r.id)}" data-search="${esc((r.patient_name + ' ' + r.pseudo_id).toLocaleLowerCase())}"><td><b>${esc(r.patient_name || 'Nama belum diisi')}</b></td><td>${r.age} tahun</td><td>${r.sex === 'L' ? 'Laki-laki' : 'Perempuan'}</td><td>${badge(r.id)}</td></tr>`).join('')}</tbody></table></div>`;
  let body = '<p class="sub">Pilih rekam di sebelah kiri.</p>';
  if (d && w) body = `<label for="f-history">Riwayat</label><textarea id="f-history" maxlength="500">${esc(d.history)}</textarea>
    <label for="f-diagnosis">Diagnosis lanjutan</label><textarea id="f-diagnosis" maxlength="1000">${esc(d.diagnosis)}</textarea>
    <label for="f-notes">Catatan klinis</label><textarea id="f-notes" maxlength="1000">${esc(d.notes)}</textarea>
    <p class="sub">Versi saat ini: v${d.version}. Menyimpan membuat versi baru dan mencatat hash baru di blockchain.</p>
    <div class="row"><button class="btn" data-action="save">Simpan sebagai versi baru</button></div>`;
  else if (d) body = `<dl><dt>Nama pasien</dt><dd>${esc(selected.patient_name || 'Nama belum diisi')} (${d.sex === 'L' ? 'laki-laki' : 'perempuan'}, ${d.age} tahun)</dd><dt>Riwayat</dt><dd>${esc(d.history)}</dd><dt>Diagnosis</dt><dd>${esc(d.diagnosis)}</dd><dt>Catatan klinis</dt><dd>${esc(d.notes)}</dd><dt>Versi</dt><dd>v${d.version}</dd></dl>
    <p class="sub">${S.role === 'dokter' && !selected.can_edit ? 'Akses rekam ini hanya baca. Minta admin memeriksa izin akses dokter.' : S.role === 'dokter' ? 'Anda dapat memperbarui diagnosis dan catatan klinis.' : 'Rekam medis hanya dapat diubah oleh dokter yang diberi akses.'}</p>`;
  return head('Rekam Medis Terintegrasi', 'Cari pasien berdasarkan nama, lalu tinjau rekam dan diagnosis sesuai izin akses.') +
    (S.records.length ? `<div class="split"><div class="list">${list}</div><div class="card">${body}</div></div>` : empty());
}
function ecgView() {
  const eligible = S.records.filter((r) => r.ecg_available);
  if (!eligible.length) return head('Visualisasi ECG', 'ECG hanya tersedia untuk pasien rawat inap dan pemulihan pascaoperasi.') + '<div class="card">Belum ada pasien yang memenuhi syarat untuk menampilkan ECG.</div>';
  const s = S.st[S.sel];
  return head('Visualisasi ECG', 'Sinyal diambil dari server. Geser untuk memilih rentang waktu; tanda R menunjukkan puncak QRS.') + picker() +
  `<div class="card"><canvas id="cv" role="img" aria-label="Grafik sinyal ECG"></canvas>
  <div class="ctl"><label>Mulai <input type="range" min="0" max="6" step=".5" value="${S.win.s}" data-range="s"> <output>${S.win.s} s</output></label>
  <label>Durasi <input type="range" min="2" max="8" step=".5" value="${S.win.d}" data-range="d"> <output>${S.win.d} s</output></label></div>
  <div class="row"><span>Biosignal: ${!s ? '<span class="b n">Belum diverifikasi</span>' : s.ecg_ok ? '<span class="b ok">✓ Sesuai hash on-chain</span>' : '<span class="b bad">⚠ Tidak sesuai hash on-chain</span>'}</span>${['admin','auditor'].includes(S.role) ? '<button class="btn alt" data-action="verify">Verifikasi integritas</button>' : '<span class="hint">Status hanya baca</span>'}</div></div>`;
}
function trackingView() {
  return head('Tracking Pasien', 'Riwayat rawat inap, tindakan, dokter penanggung jawab, dan aktivitas klinis pasien.') +
    `<div class="card tw"><table><thead><tr><th>Waktu</th><th>Pasien</th><th>Aktivitas</th><th>Dokter penanggung jawab</th><th>Spesialisasi</th><th>Dicatat oleh</th></tr></thead><tbody>${S.activities.map((a) => `<tr><td>${esc(new Date(a.occurred_at).toLocaleString('id-ID'))}</td><td><b>${esc(a.patient_name)}</b></td><td>${esc(a.description)}</td><td>${esc(a.doctor_name || '—')}</td><td>${esc(a.specialty || '—')}</td><td>${esc(a.actor)}</td></tr>`).join('') || '<tr><td colspan="6">Belum ada aktivitas tercatat.</td></tr>'}</tbody></table></div>`;
}
function intView() {
  if (!S.records.length) return head('Cek Integritas', '') + empty();
  const s = S.st[S.sel], on = s && s.onchain, lc = s && s.local;
  const cls = (a, b) => (s && on ? (a === b ? ' v' : ' x') : '');
  const msg = !s ? '' : s.status === 'valid' ? 'Hash PostgreSQL sama dengan hash on-chain. Data tidak berubah sejak dicatat.' :
    s.status === 'modified' ? 'Hash tidak cocok pada ' + [!s.record_ok && 'rekam medis', !s.ecg_ok && 'biosignal ECG'].filter(Boolean).join(' dan ') + '.' : 'Rekam ini belum tercatat di blockchain.';
  const canVerify = ['admin','auditor'].includes(S.role);
  return head('Cek Integritas', canVerify ? 'Verifikasi hash rekam medis dan ECG terhadap catatan smart contract.' : 'Lihat status integritas rekam medis dan ECG. Verifikasi dijalankan oleh admin atau auditor.') +
  `<div class="row"><label for="ps">Pasien</label><select id="ps" data-action="pick">${S.records.map((r) => `<option value="${esc(r.id)}"${r.id === S.sel ? ' selected' : ''}>${esc(r.patient_name || r.pseudo_id)}</option>`).join('')}</select>
  ${canVerify ? '<button class="btn" data-action="verify">Verifikasi sekarang</button><button class="btn alt" data-action="verifyAll">Verifikasi semua</button>' : '<span class="hint">Mode hanya baca</span>'}</div>` +
  (s ? `<div class="ban ${s.status === 'valid' ? 'ok' : 'bad'}">${ic(s.status === 'valid' ? 'ok' : 'warn')}<div>${s.status === 'valid' ? 'Valid' : (s.status === 'modified' ? 'Termodifikasi' : 'Belum terdaftar')}<small>${esc(msg)}</small></div></div>` : '') +
  `<div class="cmp"><div class="card"><b>PostgreSQL (off-chain)</b><div class="lab">Hash rekam medis, dihitung ulang</div><div class="hash${cls(lc && lc.hash_record, on && on.hash_record)}">${lc ? esc(lc.hash_record) : 'Belum dihitung'}</div>
  <div class="lab">Hash biosignal ECG, dihitung ulang</div><div class="hash${cls(lc && lc.hash_ecg, on && on.hash_ecg)}">${lc ? esc(lc.hash_ecg) : 'Belum dihitung'}</div></div>
  <div class="card"><b>Smart contract (on-chain)</b><div class="lab">Hash rekam medis tercatat</div><div class="hash">${on ? esc(on.hash_record) : '-'}</div>
  <div class="lab">Hash biosignal ECG tercatat</div><div class="hash">${on ? esc(on.hash_ecg) : '-'}</div>
  <div class="lab">${on ? 'Versi on-chain: ' + esc(on.version) : ''}</div></div></div>` +
  `<div class="card tw"><table><tr><th>Nama pasien</th><th>Status terakhir</th></tr>${S.records.map((r) => `<tr><td>${esc(r.patient_name || 'Nama belum diisi')}</td><td>${badge(r.id)}</td></tr>`).join('')}</table></div>`;
}
function aclView() {
  const adm = S.role === 'admin';
  const rows = S.records.map((r) => `<tr><td>${esc(r.patient_name || 'Nama belum diisi')}</td>${['dokter', 'pasien', 'auditor'].map((k) => { const on = S.acl[r.id] && S.acl[r.id][k];
    return `<td><button class="tg ${on ? 'on' : 'off'}" ${adm ? '' : 'disabled'} data-action="tog" data-id="${esc(r.id)}" data-role="${k}">${on ? 'Diizinkan' : 'Dicabut'}</button></td>`; }).join('')}</tr>`).join('');
  return head('Kontrol Akses', 'Izin per rekam dan peran. Perubahan dicatat sebagai AccessGranted/AccessRevoked. Admin selalu dapat membaca.') +
    `<div class="card tw"><table><tr><th>Rekam</th><th>Dokter</th><th>Pasien</th><th>Auditor</th></tr>${rows}</table></div>` +
    `<p class="sub">${adm ? 'Ubah izin, lalu masuk dengan peran lain untuk melihat dampaknya.' : 'Peran auditor hanya dapat melihat izin.'}</p>`;
}
function audView() {
  const ok = S.chainOk;
  return head('Audit Trail', 'Log basis data berantai hash dan event smart contract, diurutkan dari yang terbaru.') +
    (ok ? `<div class="ban ${ok.intact ? 'ok' : 'bad'}">${ok.intact ? '✓ Rantai audit utuh' : '⚠ Rantai audit rusak'}<small>${ok.intact ? 'Tidak ada baris log yang diubah atau dihapus di tengah rantai.' : 'Perubahan terdeteksi pada entri #' + esc(ok.first_broken_id) + '.'}</small></div>` : '') +
    `<div class="card tw"><table><tr><th>Waktu (UTC)</th><th>Pelaku</th><th>Kejadian</th><th>Hasil</th><th>Keterangan</th></tr>${S.audit.map((a) => `<tr><td>${esc(a.ts.replace('T', ' ').replace('Z', ''))}</td><td>${esc(a.actor)} (${esc(a.role || '-')})</td><td><b>${esc(a.action)}</b></td><td>${esc(a.outcome)}</td><td>${esc(a.detail)} ${a.tx_hash ? `<span class="mono">${esc(a.tx_hash.slice(0, 10))}…${esc(a.tx_hash.slice(-6))}</span>` : ''}</td></tr>`).join('')}</table></div>`;
}
function tmpView() {
  return head('Simulasi Tampering', 'Bayangkan pihak dengan akses langsung ke PostgreSQL mengubah data tanpa lewat API. Smart contract tidak ikut berubah, sehingga selisihnya terdeteksi saat verifikasi.') +
  (S.records.length ? picker() + `<div class="card"><div class="row"><button class="btn red" data-action="tamper" data-t="diagnosis">Ubah diagnosis</button><button class="btn red" data-action="tamper" data-t="notes">Ubah catatan klinis</button><button class="btn red" data-action="tamper" data-t="ecg">Sisipkan lonjakan di ECG</button></div>
  <div class="row"><button class="btn" data-action="verifyGo">Jalankan verifikasi</button><button class="btn alt" data-action="restore">Pulihkan data asli</button></div></div>` : empty());
}
function usersView() {
  const u = S.users.find((x) => x.id === S.editUser), edit = Boolean(u);
  const options = ['admin','auditor','dokter','pasien'].map((r) => `<option value="${r}"${(u ? u.role : 'dokter') === r ? ' selected' : ''}>${esc(ROLES[r].n)}</option>`).join('');
  return head('Kelola Pengguna', 'Buat akun dan kelola data profil, peran, status, serta kata sandi pengguna.') +
    `<div class="card"><h3>${edit ? 'Edit pengguna: ' + esc(u.username) : 'Tambah pengguna'}</h3><form id="user-form" data-edit="${edit ? u.id : ''}">
    <div class="cmp"><div><label>Nama lengkap</label><input name="full_name" required maxlength="120" value="${edit ? esc(u.full_name) : ''}"></div><div><label>Username</label><input name="username" required minlength="3" maxlength="40" pattern="[A-Za-z0-9_.-]+" value="${edit ? esc(u.username) : ''}"></div>
    <div><label>${edit ? 'Kata sandi baru (opsional)' : 'Kata sandi'}</label><input name="password" type="password" minlength="8" maxlength="128" ${edit ? '' : 'required'} autocomplete="new-password"></div><div><label>Peran</label><select name="role" ${edit && u.patient_id ? 'disabled' : ''}>${options}</select></div><div><label>Spesialisasi dokter</label><select name="specialty">${['Penyakit Dalam','Jantung','Bedah','Saraf','Ortopedi','Anak','Paru','Kebidanan'].map((s) => `<option value="${s}"${edit && u.specialty === s ? ' selected' : ''}>${s}</option>`).join('')}</select></div>
    <div><label>Tanggal lahir</label><input name="birth_date" type="date" value="${edit && u.birth_date ? esc(u.birth_date) : ''}"></div><div><label>Jenis kelamin</label><select name="sex"><option value="">Pilih</option><option value="L"${edit && u.sex === 'L' ? ' selected' : ''}>Laki-laki</option><option value="P"${edit && u.sex === 'P' ? ' selected' : ''}>Perempuan</option></select></div>
    <div><label>Email</label><input name="email" type="email" maxlength="254" value="${edit ? esc(u.email) : ''}"></div><div><label>Nomor telepon</label><input name="phone" maxlength="30" value="${edit ? esc(u.phone) : ''}"></div></div>
    <label>Alamat</label><textarea name="address" maxlength="1000">${edit ? esc(u.address) : ''}</textarea>
    ${edit ? `<label>Status akun</label><select name="is_active"><option value="true"${u.is_active ? ' selected' : ''}>Aktif</option><option value="false"${!u.is_active ? ' selected' : ''}>Nonaktif</option></select>` : ''}
    <div class="row"><button class="btn" type="submit">${edit ? 'Simpan perubahan' : 'Buat akun'}</button>${edit ? '<button class="btn alt" type="button" data-action="cancelUser">Batal</button>' : ''}</div></form></div>
    <div class="card tw"><table><tr><th>Pengguna</th><th>Profil</th><th>Peran</th><th>Kontak</th><th>Status</th><th>Aksi</th></tr>${S.users.map((x) => `<tr><td><b>${esc(x.username)}</b><br>${esc(x.full_name)}</td><td>${x.birth_date ? esc(x.birth_date) : '—'}${x.sex ? ' · ' + (x.sex === 'L' ? 'Laki-laki' : 'Perempuan') : ''}<br>${esc(x.address || '')}</td><td>${esc(ROLES[x.role].n)}</td><td>${esc(x.email || '—')}<br>${esc(x.phone || '')}</td><td>${x.is_active ? 'Aktif' : 'Nonaktif'}</td><td><button class="btn alt" data-action="editUser" data-id="${x.id}">Edit</button> ${x.id !== S.user.id ? `<button class="btn red" data-action="deleteUser" data-id="${x.id}">Hapus</button>` : '<span class="hint">Akun aktif</span>'}</td></tr>`).join('')}</table></div>`;
}
function invoicesView() {
  const manage = ['admin','auditor'].includes(S.role), inv = S.invoices.find((x) => x.id === S.editInvoice);
  const form = manage ? `<div class="card"><h3>${inv ? 'Edit tagihan #' + inv.id : 'Buat tagihan'}</h3><form id="invoice-form" data-edit="${inv ? inv.id : ''}">
    <label>Pasien</label><select name="patient_id" required ${inv ? 'disabled' : ''}>${S.records.map((r) => `<option value="${esc(r.id)}"${(inv ? inv.patient_id : S.sel) === r.id ? ' selected' : ''}>${esc(r.patient_name || r.pseudo_id)} · ${r.age} th</option>`).join('')}</select>
    <label>Rincian tagihan</label><input name="description" maxlength="240" required value="${inv ? esc(inv.description) : ''}">
    <div class="cmp"><div><label>Jumlah (Rp)</label><input name="amount" type="number" min="0.01" step="0.01" required value="${inv ? inv.amount : ''}"></div><div><label>Jatuh tempo</label><input name="due_date" type="date" required value="${inv ? esc(inv.due_date) : ''}"></div></div>
    <label>Status</label><select name="status"><option value="belum_lunas"${!inv || inv.status === 'belum_lunas' ? ' selected' : ''}>Belum lunas</option><option value="lunas"${inv && inv.status === 'lunas' ? ' selected' : ''}>Lunas</option></select>
    <div class="row"><button class="btn" type="submit">${inv ? 'Simpan tagihan' : 'Terbitkan tagihan'}</button>${inv ? '<button class="btn alt" type="button" data-action="cancelInvoice">Batal</button>' : ''}</div></form></div>` : '';
  const money = new Intl.NumberFormat('id-ID', {style:'currency', currency:'IDR', maximumFractionDigits:2});
  return head('Tagihan Pasien', manage ? 'Buat dan kelola jumlah tagihan, rincian layanan, serta tanggal jatuh tempo.' : 'Daftar tagihan pasien. Informasi ini hanya dapat dilihat.') + form +
    `<div class="card tw"><table><tr><th>Pasien</th><th>Rincian</th><th>Jumlah</th><th>Jatuh tempo</th><th>Status</th>${manage ? '<th>Aksi</th>' : ''}</tr>${S.invoices.map((x) => `<tr><td>${esc(x.patient_name)}</td><td>${esc(x.description)}</td><td>${money.format(x.amount)}</td><td>${esc(x.due_date)}</td><td>${x.status === 'lunas' ? 'Lunas' : 'Belum lunas'}</td>${manage ? `<td><button class="btn alt" data-action="editInvoice" data-id="${x.id}">Edit</button> <button class="btn red" data-action="deleteInvoice" data-id="${x.id}">Hapus</button></td>` : ''}</tr>`).join('') || `<tr><td colspan="${manage ? 6 : 5}">Belum ada tagihan.</td></tr>`}</table></div>`;
}
function profileView() {
  const canUpload = ['admin', 'dokter', 'auditor'].includes(S.role);
  const photo = S.user.photo_data_url;
  return `<section class="card self-profile"><div class="self-photo">${photo ? `<img src="${esc(photo)}" alt="Foto profil">` : `<span>${esc((S.user.full_name || S.user.username).slice(0,1).toUpperCase())}</span>`}</div><div class="self-info"><span class="chip">${esc(ROLES[S.role].n)}</span><h2>${esc(S.user.full_name || S.user.username)}</h2><p>@${esc(S.user.username)}</p>${canUpload ? `<label class="btn alt photo-upload">${photo ? 'Ganti foto profil' : 'Tambah foto profil'}<input type="file" data-action="photo" accept="image/jpeg,image/png,image/webp"><small>JPEG, PNG, atau WebP · maksimal 2 MB</small></label>` : '<small>Foto profil dapat ditambahkan oleh admin, dokter, atau auditor.</small>'}</div><dl class="self-fields">${[['Username',S.user.username],['Nama lengkap',S.user.full_name],['Tanggal lahir',S.user.birth_date],['Jenis kelamin',S.user.sex === 'L' ? 'Laki-laki' : S.user.sex === 'P' ? 'Perempuan' : '—'],['Spesialisasi',S.user.specialty],['Email',S.user.email],['Nomor telepon',S.user.phone],['Alamat',S.user.address]].map(([k,v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v || 'Belum diisi')}</dd></div>`).join('')}</dl></section>`;
}
function shell() {
  const nav = NAV[S.role].filter((v) => v !== 'ecg' || S.records.some((r) => r.ecg_available)).map((v) => `<button data-action="go" data-v="${v}" aria-current="${v === S.view}">${ic(v)}${VIEWS[v]}</button>`).join('');
  const V = {dash: dashView, rm: rmView, ecg: ecgView, int: intView, tracking: trackingView, acl: aclView, aud: audView, tmp: tmpView, users: usersView, invoices: invoicesView, profile: profileView};
  return `<div class="shell"><aside class="side"><div class="brand">${LOGO}MediChain</div><nav aria-label="Menu">${nav}</nav>
  <div class="foot"><div class="u"><div class="av">${esc(S.user.username[0])}</div><span><b>${esc(S.user.username)}</b><br><span class="chip">${esc(ROLES[S.role].n)}</span></span></div><button class="btn alt" data-action="logout">${ic('out')}Keluar</button></div></aside>
  <div class="mc"><div class="top"><span class="pill">PostgreSQL terhubung</span><span class="pill">Ledger blockchain aktif</span><span class="pill">SHA-256</span><button class="btn alt top-logout" data-action="logout">${ic('out')}Keluar</button></div><main>${V[S.view]()}</main></div></div>`;
}
function render() {
  $('#app').innerHTML = S.booting ? '<main class="lside"><div class="lbox"><h2>Memulihkan sesi…</h2><p class="sub">Memuat kembali ruang kerja Anda.</p></div></main>' : S.restoreError ? `<main class="lside"><div class="lbox"><h2>Sesi tersimpan</h2><p class="sub">${esc(S.restoreError)}</p><button class="btn" data-action="restore">Coba lagi</button> <button class="btn alt" data-action="logout">Keluar</button></div></main>` : S.token ? shell() : loginView();
  if (!S.token && S.err) { const p = $('#p'); if (p) p.focus(); }
  if (S.token && S.view === 'ecg') {
    if (S.ecgFrame) cancelAnimationFrame(S.ecgFrame);
    draw();
  }
  else if (S.ecgFrame) { cancelAnimationFrame(S.ecgFrame); S.ecgFrame = null; }
}
function draw() {
  if (S.ecgFrame) cancelAnimationFrame(S.ecgFrame);
  S.ecgFrame = null;
  const c = $('#cv'); if (!c || !S.ecg || S.view !== 'ecg') return;
  const cs = getComputedStyle(document.documentElement), col = (n) => cs.getPropertyValue(n).trim();
  const w = c.clientWidth, h = c.clientHeight, d = devicePixelRatio || 1; c.width = w * d; c.height = h * d;
  const x = c.getContext('2d'); x.scale(d, d); x.fillStyle = col('--sf'); x.fillRect(0, 0, w, h);
  const fs = S.ecg.fs, sm = S.ecg.samples, n = Math.min(sm.length, Math.floor(S.win.d * fs));
  if (n < 2) return;
  const offset = Math.floor(performance.now() * .018), start = Math.floor(S.win.s * fs);
  const idx = (i) => ((i % sm.length) + sm.length) % sm.length;
  const X = (i) => i / (n - 1) * w, Y = (v) => h * .78 - v * h * .42;
  x.lineWidth = 1; x.strokeStyle = col('--line'); x.fillStyle = col('--mut'); x.font = '11px sans-serif';
  for (let sec = 0; sec <= S.win.d; sec++) { const px = sec / S.win.d * w; x.beginPath(); x.moveTo(px, 0); x.lineTo(px, h); x.stroke(); if (sec < S.win.d) x.fillText((S.win.s + sec) + ' s', px + 3, h - 5); }
  x.strokeStyle = col('--ac'); x.lineWidth = 1.6; x.beginPath();
  for (let i = 0; i < n; i++) { const val = sm[idx(start + offset + i)]; if (i === 0) x.moveTo(X(i), Y(val)); else x.lineTo(X(i), Y(val)); } x.stroke();
  x.fillStyle = col('--ink'); let last = -999;
  for (let i = 1; i < n - 1; i++) { const k = idx(start + offset + i), v = sm[k]; if (v > .8 && v >= sm[idx(k - 1)] && v >= sm[idx(k + 1)] && i - last > fs * .16) { last = i; x.beginPath(); x.arc(X(i), Y(v) - 8, 2.5, 0, 7); x.fill(); x.fillText('R', X(i) - 3, Y(v) - 14); } }
  S.ecgFrame = requestAnimationFrame(draw);
}

// ---------- data dan aksi ----------
async function loadRecords() {
  S.records = await api('/records');
  if (!S.records.find((r) => r.id === S.sel)) S.sel = S.records.length ? S.records[0].id : null;
}
async function load(v) {
  if (v === 'rm' && S.sel) S.detail = await api('/records/' + encodeURIComponent(S.sel));
  if (v === 'ecg' && S.sel) {
    const [ecg, integrity] = await Promise.all([api('/records/' + encodeURIComponent(S.sel) + '/ecg?start=0&duration=8'), api('/records/' + encodeURIComponent(S.sel) + '/integrity')]);
    S.ecg = ecg; S.st[S.sel] = integrity;
  }
  if (v === 'int') {
    // Verification results are derived from PostgreSQL and the active chain.
    // Re-read every visible record when opening the view so a page reload does
    // not make previously checked patients look "not verified" just because
    // the old UI state lived only in memory.
    const checks = await Promise.all(S.records.map(async (r) => [
      r.id, await api('/records/' + encodeURIComponent(r.id) + '/integrity')
    ]));
    S.st = Object.fromEntries(checks);
  }
  if (v === 'acl') { S.acl = {}; await Promise.all(S.records.map(async (r) => { S.acl[r.id] = await api('/records/' + encodeURIComponent(r.id) + '/access'); })); }
  if (v === 'aud') { const [a, c] = await Promise.all([api('/audit?limit=100'), api('/audit/verify')]); S.audit = a; S.chainOk = c; }
  if (v === 'users') S.users = await api('/users');
  if (v === 'tracking') S.activities = await api('/tracking');
  if (v === 'invoices') S.invoices = await api('/invoices');
  if (v === 'profile') S.user = await api('/me');
}
async function nav(v) { if (v === 'ecg') S.sel = (S.records.find((r) => r.ecg_available) || {}).id || null; S.view = v; saveSession(); try { await load(v); } catch (e) { fail(e); } render(); }
async function verifyOne(id) { S.st[id] = await api('/records/' + encodeURIComponent(id) + '/verify', {method: 'POST'}); }
function logout(msg) { Object.assign(S, {token: null, role: null, user: null, records: [], sel: null, detail: null, ecg: null, st: {}, acl: {}, audit: [], chainOk: null, users: [], invoices: [], editUser: null, editInvoice: null, view: 'dash', err: msg || '', booting: false}); saveSession(); render(); }
async function doLogin(username, password) {
  S.err = '';
  try {
    const r = await api('/auth/login', {method: 'POST', body: {username, password}});
    S.token = r.access_token; S.role = r.role; saveSession(); S.user = await api('/me');
    S.view = 'dash'; await loadRecords(); await load('rm'); saveSession();
  } catch (e) {
    if (e.status === 401 || !S.token) {
      S.token = null; saveSession();
      S.err = e.status === 429 ? 'Terlalu banyak percobaan. Tunggu sebentar.' : e.status === 401 ? 'Username atau password salah.' : e.message;
    } else {
      S.restoreError = 'Login berhasil, tetapi server belum dapat memuat data. Periksa API lalu coba lagi.';
    }
  }
  render();
}
async function restoreSession() {
  if (!S.token) { render(); return; }
  S.restoreError = ''; render();
  try {
    S.user = await api('/me');
    S.role = S.user.role;
    if (!NAV[S.role] || !VIEWS[S.view] || !NAV[S.role].includes(S.view)) S.view = 'dash';
    await loadRecords();
    await load(S.view);
    saveSession();
  } catch (e) {
    if (!e.handled) S.restoreError = 'Server belum dapat dijangkau. Periksa apakah API masih berjalan, lalu coba lagi.';
  } finally {
    S.booting = false;
    render();
  }
}
const A = {
  restore: () => restoreSession(),
  photo: async (input) => {
    const file = input.files && input.files[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { toast('Pilih foto JPEG, PNG, atau WebP.'); input.value = ''; return; }
    if (file.size > 2 * 1024 * 1024) { toast('Ukuran foto maksimal 2 MB.'); input.value = ''; return; }
    try {
      const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(file); });
      await api('/me/profile-photo', {method: 'PUT', body: {content_type: file.type, data: dataUrl.split(',')[1]}});
      S.user.photo_data_url = dataUrl; toast('Foto profil berhasil diperbarui.'); render();
    } catch (e) { fail(e); }
    input.value = '';
  },
  go: (b) => nav(b.dataset.v),
  pick: (b) => { S.sel = b.dataset.id || b.value; S.detail = null; saveSession(); nav(S.view); },
  save: async () => {
    try { const r = await api('/records/' + encodeURIComponent(S.sel), {method: 'PUT', body: {history: $('#f-history').value, diagnosis: $('#f-diagnosis').value, notes: $('#f-notes').value}});
      S.detail = r; delete S.st[S.sel]; toast('Tersimpan sebagai versi ' + r.version + '. Hash baru dicatat on-chain.'); } catch (e) { fail(e); }
    render();
  },
  verify: async () => { try { await verifyOne(S.sel); } catch (e) { fail(e); } render(); },
  verifyAll: async () => { for (const r of S.records) { try { await verifyOne(r.id); } catch (e) { fail(e); } } render(); },
  verifyGo: async () => { S.view = 'int'; try { await verifyOne(S.sel); } catch (e) { fail(e); } render(); },
  editUser: (b) => { S.editUser = Number(b.dataset.id); render(); },
  cancelUser: () => { S.editUser = null; render(); },
  deleteUser: async (b) => {
    const target = S.users.find((u) => u.id === Number(b.dataset.id));
    if (!target || !confirm('Hapus akun ' + target.username + '? Rekam medis pasien tetap tersimpan.')) return;
    try { await api('/users/' + target.id, {method:'DELETE'}); S.users = await api('/users'); await loadRecords(); toast('Akun pengguna dihapus.'); }
    catch (e) { fail(e); }
    render();
  },
  editInvoice: (b) => { S.editInvoice = Number(b.dataset.id); render(); },
  cancelInvoice: () => { S.editInvoice = null; render(); },
  deleteInvoice: async (b) => {
    if (!confirm('Hapus tagihan ini?')) return;
    try { await api('/invoices/' + b.dataset.id, {method:'DELETE'}); S.invoices = await api('/invoices'); toast('Tagihan dihapus.'); } catch (e) { fail(e); }
    render();
  },
  tog: async (b) => {
    const id = b.dataset.id, role = b.dataset.role, allowed = !(S.acl[id] && S.acl[id][role]);
    try { await api('/records/' + encodeURIComponent(id) + '/access/' + role, {method: 'PUT', body: {allowed}}); S.acl[id][role] = allowed; } catch (e) { fail(e); }
    render();
  },
  tamper: async (b) => {
    try { const r = await api('/dev/tamper/' + encodeURIComponent(S.sel), {method: 'POST', body: {target: b.dataset.t}}); delete S.st[S.sel]; toast(r.note); }
    catch (e) { toast(e.status === 404 ? 'Simulasi tampering nonaktif di server (ENABLE_TAMPER_SIM=false).' : e.message); }
    render();
  },
  restore: async () => { try { await api('/dev/restore/' + encodeURIComponent(S.sel), {method: 'POST'}); delete S.st[S.sel]; toast('Data dipulihkan.'); } catch (e) { fail(e); } render(); },
  logout: () => logout('')
};
document.addEventListener('click', (e) => { const b = e.target.closest('[data-action]'); if (b && b.tagName !== 'SELECT' && A[b.dataset.action]) A[b.dataset.action](b); });
document.addEventListener('change', (e) => { const s = e.target.closest('select[data-action]'); if (s && A[s.dataset.action]) { A[s.dataset.action](s); return; } const file = e.target.closest('input[type="file"][data-action="photo"]'); if (file) A.photo(file); });
document.addEventListener('input', (e) => {
  const r = e.target.closest('input[data-range]');
  if (r) { S.win[r.dataset.range] = +r.value; r.nextElementSibling.textContent = r.value + ' s'; draw(); }
  const q = e.target.closest('#patient-search');
  if (q) { const term = q.value.trim().toLocaleLowerCase(); document.querySelectorAll('#patient-table tbody tr').forEach((row) => { row.hidden = !row.dataset.search.includes(term); }); }
});
document.addEventListener('submit', (e) => { const f = e.target.closest('#lf'); if (f) { e.preventDefault(); doLogin(f.elements.username.value.trim(), f.elements.password.value); } });
document.addEventListener('submit', async (e) => {
  const uf = e.target.closest('#user-form'), inf = e.target.closest('#invoice-form');
  if (uf) {
    e.preventDefault(); const d = new FormData(uf), id = uf.dataset.edit;
    const body = {full_name:d.get('full_name'), address:d.get('address'), phone:d.get('phone'), email:d.get('email')};
    if (d.get('birth_date')) body.birth_date = d.get('birth_date');
    if (d.get('sex')) body.sex = d.get('sex');
    if (d.get('role')) body.role = d.get('role');
    if (d.get('role') === 'dokter') body.specialty = d.get('specialty');
    if (d.get('is_active')) body.is_active = d.get('is_active') === 'true';
    try {
      if (id) {
        body.username = d.get('username');
        await api('/users/' + id, {method:'PUT', body});
        if (d.get('password')) await api('/users/' + id + '/password', {method:'PUT', body:{password:d.get('password')}});
        toast('Data pengguna diperbarui.');
      } else {
        body.username = d.get('username'); body.password = d.get('password'); body.role = d.get('role');
        await api('/users', {method:'POST', body}); toast('Akun berhasil dibuat.');
      }
      S.editUser = null; S.users = await api('/users'); await loadRecords();
    } catch (err) { fail(err); }
    render();
  } else if (inf) {
    e.preventDefault(); const d = new FormData(inf), id = inf.dataset.edit;
    const body = {description:d.get('description'), amount:Number(d.get('amount')), due_date:d.get('due_date'), status:d.get('status')};
    if (!id) body.patient_id = d.get('patient_id');
    try {
      await api(id ? '/invoices/' + id : '/invoices', {method:id ? 'PUT' : 'POST', body});
      S.editInvoice = null; S.invoices = await api('/invoices'); toast(id ? 'Tagihan diperbarui.' : 'Tagihan diterbitkan.');
    } catch (err) { fail(err); }
    render();
  }
});
addEventListener('resize', draw);
restoreSession();
})();
