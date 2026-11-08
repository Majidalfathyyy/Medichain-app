'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

type Role = 'admin' | 'dokter' | 'pasien' | 'auditor';
type Row = Record<string, any>;
const roleName: Record<Role, string> = { admin: 'Admin', dokter: 'Dokter', pasien: 'Pasien', auditor: 'Auditor' };
const navByRole: Record<Role, string[]> = {
  admin: ['Ringkasan', 'Pasien', 'Rekam medis', 'Terapi & pemeriksaan', 'ECG', 'Integritas', 'Perawatan', 'Tracking', 'Jadwal', 'Permohonan', 'Tagihan', 'Pengguna', 'Audit', 'Profil saya'],
  dokter: ['Ringkasan', 'Pasien', 'Rekam medis', 'Terapi & pemeriksaan', 'ECG', 'Integritas', 'Perawatan', 'Jadwal', 'Permohonan', 'Tagihan', 'Profil saya'],
  pasien: ['Ringkasan', 'Rekam medis', 'Terapi & pemeriksaan', 'ECG', 'Integritas', 'Perawatan', 'Jadwal', 'Ajukan pemeriksaan', 'Tagihan', 'Profil saya'],
  auditor: ['Ringkasan', 'Pasien', 'Rekam medis', 'Terapi & pemeriksaan', 'ECG', 'Integritas', 'Tagihan', 'Pengguna', 'Kontrol akses', 'Audit', 'Profil saya'],
};
const endpoint: Record<string, string> = { Ringkasan: 'dash', Pasien: 'patients', 'Rekam medis': 'record', 'Terapi & pemeriksaan': 'clinical-care', ECG: 'ecg', Integritas: 'integrity', Perawatan: 'care', Tracking: 'tracking', Jadwal: 'appointments', 'Permohonan': 'requests', 'Ajukan pemeriksaan': 'request-form', Tagihan: 'invoices', Pengguna: 'users', 'Kontrol akses': 'acl', Audit: 'audit', 'Profil saya': 'profile' };
const dateLabel = (value?: string) => value ? new Date(value).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }) : '—';
const money = (amount: number) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(amount || 0);
const GOPAY_QRIS_IMAGE = process.env.NEXT_PUBLIC_GOPAY_QRIS_IMAGE || '/gopay-qris.png';
const usernameSuggestion = (fullName: string) => fullName.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/^(drs?|prof|dokter)\.?\s+/i, '').toLowerCase().match(/[a-z0-9]+/g)?.join('.') || '';
function authErrorMessage(payload: any, status: number, fallback: string) {
  if (typeof payload?.detail === 'string') return payload.detail;
  if (Array.isArray(payload?.detail)) {
    const message = payload.detail.find((item: any) => typeof item?.msg === 'string')?.msg;
    if (message) return message.replace(/^Value error,\s*/i, '');
  }
  if (status >= 500) return 'Layanan pendaftaran belum terhubung. Pastikan API FastAPI berjalan dan koneksi PostgreSQL berhasil.';
  return fallback;
}
function authNetworkError(error: unknown) {
  return error instanceof TypeError
    ? 'API MediChain belum dapat dijangkau. Jalankan FastAPI di http://localhost:8000 dan pastikan PostgreSQL aktif.'
    : (error as Error).message;
}
function simulatedEcg(seed: string, count = 2000, fs = 250) {
  let hash = 2166136261;
  for (const char of seed) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  let state = hash >>> 0 || 1;
  const random = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 4294967296; };
  const gaussian = (x: number, center: number, width: number, amplitude: number) => amplitude * Math.exp(-((x - center) ** 2) / (2 * width ** 2));
  const seconds = count / fs;
  const heartRate = 62 + Math.floor(random() * 43);
  const rrMean = 60 / heartRate;
  const phase = random() * Math.PI * 2;
  const amplitude = .9 + random() * .2;
  const tPeak = .24 + random() * .08;
  const rPeaks: number[] = [];
  let nextR = .45 + random() * .12;
  while (nextR < seconds + .5) {
    rPeaks.push(nextR);
    nextR += rrMean + (random() - .5) * .07;
  }
  return Array.from({ length: count }, (_, i) => {
    const t = i / fs;
    let signal = .025 * Math.sin(2 * Math.PI * .25 * t + phase) + .009 * Math.sin(2 * Math.PI * .08 * t + phase * .6);
    for (const peak of rPeaks) {
      const dt = t - peak;
      if (dt < -.45 || dt > .65) continue;
      signal += amplitude * (gaussian(dt, -.19, .035, .12) + gaussian(dt, -.038, .009, -.13)
        + gaussian(dt, 0, .011, 1) + gaussian(dt, .035, .012, -.24)
        + gaussian(dt, tPeak, .075, .28));
    }
    signal += .0025 * Math.sin(2 * Math.PI * 50 * t + phase) + (random() - .5) * .009;
    return Number(signal.toFixed(4));
  });
}
const navIconPath: Record<string, string> = {
  'Ringkasan': 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  'Pasien': 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M20 8v6M23 11h-6',
  'Rekam medis': 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7',
  'Terapi & pemeriksaan': 'M6 3h9l4 4v14H5V3zM14 3v5h5M8 12h8M8 16h8M8 8h2',
  'ECG': 'M2 12h5l3-7 4 14 3-7h5',
  'Integritas': 'M12 3 20 6v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6zM8 12l3 3 5-6',
  'Perawatan': 'M12 5v14M5 12h14',
  'Tracking': 'M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0zM12 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
  'Jadwal': 'M4 5h16v16H4zM8 3v4M16 3v4M4 10h16M8 14h2M14 14h2',
  'Permohonan': 'M4 4h16v13H9l-5 4zM8 9h8M8 13h5',
  'Tagihan': 'M5 3h14v18l-4-2-3 2-3-2-4 2zM8 8h8M8 12h8M8 16h5',
  'Pengguna': 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M17 4a4 4 0 0 1 0 7M20 21v-2a4 4 0 0 0-3-3.9',
  'Audit': 'M10 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M21 21l-5-5',
  'Kontrol akses': 'M6 11V8a6 6 0 0 1 12 0v3M5 11h14v10H5z',
  'Profil saya': 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21a8 8 0 0 1 16 0'
};

export default function Home() {
  const [authMode, setAuthMode] = useState<'login' | 'register' | 'registered' | 'onboarding'>('login');
  const [pendingRegistrationUsername, setPendingRegistrationUsername] = useState('');
  const [pendingGoogleToken, setPendingGoogleToken] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [token, setToken] = useState('');
  const [authReady, setAuthReady] = useState(false);
  const [role, setRole] = useState<Role>('dokter');
  const [username, setUsername] = useState('');
  const [myProfile, setMyProfile] = useState<Row | null>(null);
  const [view, setView] = useState('Ringkasan');
  const [rows, setRows] = useState<Row[]>([]);
  const [records, setRecords] = useState<Row[]>([]);
  const [query, setQuery] = useState('');
  const [ecgSearchQuery, setEcgSearchQuery] = useState('');
  const [ecgSearchOpen, setEcgSearchOpen] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [readNotifications, setReadNotifications] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [dataLoading, setDataLoading] = useState(false);
  const [upcomingCount, setUpcomingCount] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [selected, setSelected] = useState<Row | null>(null);
  const [clinical, setClinical] = useState<Row | null>(null);
  const [clinicalCare, setClinicalCare] = useState<Row | null>(null);
  const [ecg, setEcg] = useState<Row | null>(null);
  const [integrity, setIntegrity] = useState<Row | null>(null);
  const [recordDraft, setRecordDraft] = useState({ history: '', diagnosis: '', notes: '' });
  const [recordDetailOpen, setRecordDetailOpen] = useState(false);
  const [careTimeline, setCareTimeline] = useState<Row | null>(null);
  const [clinicalAlerts, setClinicalAlerts] = useState<Row[]>([]);
  const [observations, setObservations] = useState<Row[]>([]);
  const [recordShares, setRecordShares] = useState<Row[]>([]);
  const [createdShare, setCreatedShare] = useState<Row | null>(null);
  const [editingInvoice, setEditingInvoice] = useState<Row | null>(null);
  const [payingInvoice, setPayingInvoice] = useState<Row | null>(null);
  const [qrisImageUnavailable, setQrisImageUnavailable] = useState(false);
  const [paymentProofDataUrl, setPaymentProofDataUrl] = useState('');
  const [paymentProofContentType, setPaymentProofContentType] = useState('');
  const [paymentProofFileName, setPaymentProofFileName] = useState('');
  const [paymentProofError, setPaymentProofError] = useState('');
  const [paymentProofBusy, setPaymentProofBusy] = useState(false);
  const [reviewingProof, setReviewingProof] = useState<Row | null>(null);
  const [reviewProofBusy, setReviewProofBusy] = useState(false);
  const [reviewProofError, setReviewProofError] = useState('');
  const [proofRejectReason, setProofRejectReason] = useState('');
  const [editingAppointment, setEditingAppointment] = useState<Row | null>(null);
  const [editingUser, setEditingUser] = useState<Row | null>(null);
  const [passwordUser, setPasswordUser] = useState<Row | null>(null);
  const [passwordError, setPasswordError] = useState('');
  const [careStatus, setCareStatus] = useState('rawat_jalan');
  const [room, setRoom] = useState('');
  const [note, setNote] = useState('');
  const notificationItems = [
    ...(pendingCount > 0 ? [{ id: 'requests', title: `${pendingCount} permohonan pemeriksaan menunggu`, detail: 'Perlu ditinjau oleh tim layanan.', target: role === 'pasien' ? 'Jadwal' : 'Permohonan' }] : []),
    ...(upcomingCount > 0 ? [{ id: 'appointments', title: `${upcomingCount} jadwal pemeriksaan mendatang`, detail: 'Periksa jadwal layanan pasien.', target: 'Jadwal' }] : []),
  ];
  const unreadNotificationCount = notificationItems.filter((item) => !readNotifications[item.id]).length;

  useEffect(() => {
    try {
      const savedTheme = localStorage.getItem('medichain.theme');
      if (savedTheme === 'dark' || savedTheme === 'light') setTheme(savedTheme);
    } catch {}
  }, []);

  useEffect(() => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    if (token || !clientId) return;
    let cancelled = false;
    const mountButton = () => {
      const google = (window as any).google;
      const target = document.getElementById('google-signin-button');
      if (cancelled || !google?.accounts?.id || !target) return;
      google.accounts.id.initialize({ client_id: clientId, callback: async (response: { credential: string }) => {
        setAuthBusy(true); setError('');
        try {
          const result = await fetch('/api/auth/google', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential: response.credential }) });
          const payload = await result.json().catch(() => null);
          if (!result.ok) throw new Error(payload?.detail || 'Masuk dengan Google gagal.');
          if (payload?.approval_pending) { setPendingRegistrationUsername(payload.username || ''); setAuthMode('registered'); return; }
          if (!payload.profile_complete) { setPendingGoogleToken(payload.access_token); setAuthMode('onboarding'); return; }
          await activateSession(payload.access_token);
        } catch (e) { setError((e as Error).message); }
        finally { setAuthBusy(false); }
      } });
      google.accounts.id.renderButton(target, { theme: 'outline', size: 'large', text: 'continue_with', shape: 'pill', width: Math.min(380, target.clientWidth || 380), locale: 'id' });
    };
    const existing = document.querySelector('script[data-google-identity]') as HTMLScriptElement | null;
    if (existing) { if ((window as any).google?.accounts?.id) mountButton(); else existing.addEventListener('load', mountButton, { once: true }); }
    else { const script = document.createElement('script'); script.src = 'https://accounts.google.com/gsi/client'; script.async = true; script.defer = true; script.dataset.googleIdentity = 'true'; script.onload = mountButton; document.head.appendChild(script); }
    return () => { cancelled = true; };
  }, [token, authMode]);

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    try { localStorage.setItem('medichain.theme', nextTheme); } catch {}
  }

  const api = useCallback(async (path: string, method = 'GET', body?: Row) => {
    const response = await fetch(`/api${path}`, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => null);
    if (response.status === 401 && token) {
      try { sessionStorage.removeItem('medichain.session'); } catch {}
      setToken(''); setRole('dokter'); setUsername(''); setError('Sesi berakhir. Silakan masuk kembali.');
    }
    if (!response.ok) throw new Error(data?.detail || `Permintaan gagal (${response.status})`);
    return data;
  }, [token]);

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      let saved: Row | null = null;
      try { saved = JSON.parse(sessionStorage.getItem('medichain.session') || 'null'); } catch {}
      if (!saved?.token) { if (active) setAuthReady(true); return; }
      try {
        const response = await fetch('/api/me', { headers: { Authorization: `Bearer ${saved.token}` } });
        if (response.status === 401) {
          sessionStorage.removeItem('medichain.session');
          if (active) setError('Sesi berakhir. Silakan masuk kembali.');
        } else if (!response.ok) {
          throw new Error('API tidak tersedia');
        } else {
          const me = await response.json();
          if (!navByRole[me?.role as Role]) {
            sessionStorage.removeItem('medichain.session');
            if (active) setError('Peran akun tidak dikenali. Silakan masuk kembali.');
            return;
          }
          if (active) {
            const userRole = me.role as Role;
            setToken(saved.token); setRole(userRole); setUsername(me.username); setMyProfile(me);
            if (navByRole[userRole]?.includes(saved.view)) setView(saved.view);
            if (saved.selectedId) setSelected({ id: saved.selectedId });
          }
        }
      } catch {
        if (active) {
          const savedRole: Role = navByRole[saved.role as Role] ? saved.role as Role : 'dokter';
          setToken(saved.token); setRole(savedRole); setUsername(saved.username || '');
          if (navByRole[savedRole].includes(saved.view)) setView(saved.view);
          if (saved.selectedId) setSelected({ id: saved.selectedId });
          setError('API belum dapat dijangkau. Sesi dipertahankan; muat ulang setelah API aktif.');
        }
      } finally { if (active) setAuthReady(true); }
    }
    void restoreSession();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!authReady) return;
    try {
      if (token) sessionStorage.setItem('medichain.session', JSON.stringify({ token, role, username, view, selectedId: selected?.id || null }));
      else sessionStorage.removeItem('medichain.session');
    } catch {}
  }, [authReady, token, role, username, view, selected?.id]);

  const load = useCallback(async (target = view) => {
    if (!token) return;
    const route = endpoint[target] || target;
    setError('');
    setDataLoading(true);
    try {
      const [patientRows, careRows] = await Promise.all([api('/records'), api('/care')]);
      if (!Array.isArray(patientRows) || !Array.isArray(careRows)) throw new Error('Format data pasien/perawatan dari API tidak sesuai. Muat ulang halaman atau periksa layanan API.');
      setRecords(patientRows);
      const careById = new Map(careRows.map((r: Row) => [r.patient_id, r]));
      const merged = patientRows.map((p: Row) => ({ ...p, ...(careById.get(p.id) || {}) }));
      const selectedId = selected?.id;
      const selectedRecord = selected ? merged.find((r: Row) => r.id === selected.id) : null;
      const activeSelection = selectedRecord || (view === 'ECG'
        ? merged.find((r: Row) => r.ecg_available) || merged[0]
        : merged[0]);
      if (selected && !selectedRecord) {
        setClinical(null);
        setEcg(null);
        setIntegrity((prev) => {
          if (!merged.length) return null;
          if (!prev || !selectedId || !Object.prototype.hasOwnProperty.call(prev, selectedId)) return prev;
          const next = { ...prev };
          delete next[selectedId];
          return next;
        });
        setSelected(activeSelection || null);
      } else if (!selected && merged.length) {
        setSelected(activeSelection || null);
      } else if (selected && selectedRecord && (
        selected.patient_name !== selectedRecord.patient_name ||
        selected.ecg_available !== selectedRecord.ecg_available ||
        selected.care_status !== selectedRecord.care_status ||
        selected.room !== selectedRecord.room
      )) {
        setSelected(selectedRecord);
        if (!selectedRecord.ecg_available) setEcg(null);
      } else if (!merged.length && selected) {
        setSelected(null);
        setClinical(null);
        setEcg(null);
        setIntegrity(null);
      }
      if (route === 'dash') {
        const [appointments, requests, integrityChecks] = await Promise.all([
          api('/appointments'),
          api('/appointment-requests'),
          Promise.all(patientRows.map(async (record: Row) => {
            try {
              const result = await api(`/records/${record.id}/integrity`);
              return [record.id, result.status] as const;
            } catch {
              return [record.id, 'unavailable'] as const;
            }
          })),
        ]);
        setUpcomingCount(appointments.filter((x: Row) => x.status === 'terjadwal').length);
        setPendingCount(requests.filter((x: Row) => !['disetujui', 'ditolak'].includes(x.status)).length);
        const statusByRecord = Object.fromEntries(integrityChecks);
        setRows(merged.map((record: Row) => ({
          ...record,
          integrity_status: statusByRecord[record.id] || 'unavailable',
        })));
      }
      if (route === 'patients' || route === 'care') setRows(merged);
      else if (route === 'appointments') setRows(await api('/appointments'));
      else if (route === 'requests') setRows(await api('/appointment-requests'));
      else if (route === 'invoices') setRows(await api('/invoices'));
      else if (route === 'users') setRows(await api('/users'));
      else if (route === 'profile') setMyProfile(await api('/me'));
      else if (route === 'tracking') setRows(await api('/tracking'));
      else if (route === 'audit') setRows(await api('/audit'));
      else if (route === 'record' && activeSelection?.id) {
        const detail = await api(`/records/${activeSelection.id}`); setClinical(detail);
        setRecordDraft({ history: detail.history, diagnosis: detail.diagnosis, notes: detail.notes });
        if (recordDetailOpen) {
          const [timeline, alerts, vitalRows] = await Promise.all([
            api(`/records/${activeSelection.id}/timeline`),
            api(`/records/${activeSelection.id}/alerts`),
            api(`/records/${activeSelection.id}/observations`),
          ]);
          setCareTimeline(timeline); setClinicalAlerts(alerts.alerts || []); setObservations(vitalRows || []);
          if (role === 'pasien') setRecordShares(await api(`/records/${activeSelection.id}/shares`));
          else setRecordShares([]);
        }
      }
      else if (route === 'clinical-care' && activeSelection?.id) {
        setClinicalCare(await api(`/records/${activeSelection.id}/clinical`));
      }
      else if (route === 'ecg' && activeSelection?.id && activeSelection.ecg_available) setEcg(await api(`/records/${activeSelection.id}/ecg?start=0&duration=8`));
      else if (route === 'integrity') {
        const checks = await Promise.all(patientRows.map(async (r: Row) => ({ ...r, ...(await api(`/records/${r.id}/integrity`)) })));
        setRows(checks);
      }
      else if (route === 'acl') {
        const access = await Promise.all(patientRows.map(async (r: Row) => ({ name: r.patient_name, id: r.id, roles: await api(`/records/${r.id}/access`) })));
        setRows(access);
      }
    } catch (e) { setError((e as Error).message); }
    finally { setDataLoading(false); }
  }, [api, recordDetailOpen, role, selected, token, view]);

  useEffect(() => { if (token) void load(); }, [token, view, load]);

  const filtered = useMemo(() => rows.filter((r) => JSON.stringify(r).toLocaleLowerCase().includes(query.toLocaleLowerCase())), [rows, query]);
  const filteredRecords = useMemo(() => records.filter((r) => JSON.stringify({ name: r.patient_name, id: r.pseudo_id, room: r.room, status: r.care_status, doctor: r.doctor_name }).toLocaleLowerCase().includes(query.toLocaleLowerCase())), [records, query]);
  async function activateSession(accessToken: string) {
    const meResponse = await fetch('/api/me', { headers: { Authorization: `Bearer ${accessToken}` } });
    const me = await meResponse.json().catch(() => null);
    if (!meResponse.ok || !me || !navByRole[me.role as Role]) throw new Error('Sesi berhasil dibuat, tetapi profil akun gagal dimuat.');
    setMyProfile(me); setToken(accessToken); setRole(me.role as Role); setUsername(me.username); setView('Ringkasan'); setAuthMode('login'); setPendingGoogleToken('');
  }

  async function finishGoogleRegistration(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setAuthBusy(true); setError('');
    const form = new FormData(e.currentTarget);
    try {
      const response = await fetch('/api/auth/complete-registration', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${pendingGoogleToken}` }, body: JSON.stringify({ birth_date: form.get('birth_date'), sex: form.get('sex'), phone: form.get('phone'), address: form.get('address') }) });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(authErrorMessage(payload, response.status, 'Profil pasien belum dapat dilengkapi.'));
      await activateSession(pendingGoogleToken);
      setNotice('Pendaftaran Google berhasil. Rekam medis awal telah dibuat.');
    } catch (e) { setError(authNetworkError(e)); }
    finally { setAuthBusy(false); }
  }

  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError('');
    const data = new FormData(e.currentTarget);
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: data.get('username'), password: data.get('password') }) });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof payload?.detail === 'string' ? payload.detail : response.status >= 500 ? 'Layanan API sedang tidak tersedia. Pastikan backend FastAPI berjalan di http://localhost:8000.' : 'Gagal masuk. Periksa kembali username dan password.');
      if (!payload?.access_token || !payload?.role) throw new Error('Balasan login tidak lengkap. Periksa koneksi API lalu coba lagi.');
      if (!navByRole[payload.role as Role]) throw new Error('Peran akun tidak dikenali. Hubungi administrator.');
      const meResponse = await fetch('/api/me', { headers: { Authorization: `Bearer ${payload.access_token}` } });
      const me = await meResponse.json().catch(() => null);
      if (!meResponse.ok || !me) throw new Error('Login berhasil, tetapi profil akun gagal dimuat. Coba lagi.');
      setMyProfile(me);
      setToken(payload.access_token); setRole(payload.role as Role); setUsername(String(data.get('username'))); setView('Ringkasan');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function registerPatient(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setAuthBusy(true); setError('');
    const data = new FormData(e.currentTarget);
    const password = String(data.get('password') || '');
    if (password !== String(data.get('confirm_password') || '')) {
      setError('Konfirmasi kata sandi belum cocok.'); setAuthBusy(false); return;
    }
    try {
      const response = await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(data.entries())) });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(authErrorMessage(payload, response.status, 'Pendaftaran belum dapat diproses. Periksa kembali data Anda.'));
      setPendingRegistrationUsername(String(payload?.username || data.get('username') || ''));
      setAuthMode('registered'); setError('');
    } catch (e) { setError(authNetworkError(e)); }
    finally { setAuthBusy(false); }
  }
  function logout() {
    try { sessionStorage.removeItem('medichain.session'); } catch {}
    setToken(''); setRole('dokter'); setUsername(''); setMyProfile(null); setView('Ringkasan');
    setRows([]); setRecords([]); setSelected(null); setClinical(null); setEcg(null); setIntegrity(null);
    setError(''); setNotice(''); setNotificationsOpen(false);
  }
  async function run(action: () => Promise<unknown>, message: string) {
    try { const result = await action() as Row; setNotice(result?.chain_sync_pending || result?.pending_count ? 'Data tersimpan; sebagian transaksi masih menunggu konfirmasi blockchain.' : message); setError(''); await load(); setTimeout(() => setNotice(''), 5000); }
    catch (e) { setError((e as Error).message); }
  }

  function selectPaymentProof(file?: File) {
    setPaymentProofError('');
    setPaymentProofDataUrl('');
    setPaymentProofContentType('');
    setPaymentProofFileName('');
    if (!file) return;
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      setPaymentProofError('Pilih gambar JPG, PNG, atau WebP.');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setPaymentProofError('Ukuran gambar maksimal 2 MB.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        setPaymentProofError('Gambar tidak dapat dibaca. Silakan pilih ulang.');
        return;
      }
      setPaymentProofDataUrl(reader.result);
      setPaymentProofContentType(file.type);
      setPaymentProofFileName(file.name);
    };
    reader.onerror = () => setPaymentProofError('Gambar tidak dapat dibaca. Silakan pilih ulang.');
    reader.readAsDataURL(file);
  }

  async function submitPaymentProof(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!payingInvoice || !paymentProofDataUrl || !paymentProofContentType) {
      setPaymentProofError('Pilih bukti pembayaran terlebih dahulu.');
      return;
    }
    setPaymentProofBusy(true);
    setPaymentProofError('');
    try {
      const encodedImage = paymentProofDataUrl.split(',', 2)[1];
      await api(`/invoices/${payingInvoice.id}/payment-proofs`, 'POST', {
        content_type: paymentProofContentType,
        data: encodedImage,
      });
      setNotice('Bukti pembayaran terkirim. Status tagihan menunggu verifikasi admin.');
      setError('');
      (document.getElementById('payment-dialog') as HTMLDialogElement)?.close();
      await load();
      setTimeout(() => setNotice(''), 5000);
    } catch (err) {
      setPaymentProofError((err as Error).message);
    } finally {
      setPaymentProofBusy(false);
    }
  }

  async function openPaymentProof(proofId: number) {
    setReviewProofError('');
    setProofRejectReason('');
    try {
      const proof = await api(`/payment-proofs/${proofId}`);
      setReviewingProof(proof);
      (document.getElementById('payment-review-dialog') as HTMLDialogElement)?.showModal();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function reviewPaymentProof(decision: 'approve' | 'reject') {
    if (!reviewingProof) return;
    if (decision === 'reject' && !proofRejectReason.trim()) {
      setReviewProofError('Isi alasan penolakan agar pasien tahu perbaikannya.');
      return;
    }
    setReviewProofBusy(true);
    setReviewProofError('');
    try {
      const result = await api(`/payment-proofs/${reviewingProof.id}/review`, 'POST', {
        decision,
        reason: decision === 'reject' ? proofRejectReason.trim() : '',
      });
      setNotice(result.status === 'approved'
        ? 'Bukti disetujui. Tagihan ditandai lunas.'
        : 'Bukti ditolak. Pasien dapat mengunggah bukti baru.');
      setError('');
      (document.getElementById('payment-review-dialog') as HTMLDialogElement)?.close();
      await load();
      setTimeout(() => setNotice(''), 5000);
    } catch (err) {
      setReviewProofError((err as Error).message);
    } finally {
      setReviewProofBusy(false);
    }
  }

  async function decideAppointmentRequest(id: number, decision: 'setujui' | 'tolak') {
    try {
      const result = await api(`/appointment-requests/${id}/decision`, 'POST', { decision }) as Row;
      setNotice(result.status === 'disetujui'
        ? 'Permohonan disetujui dokter dan admin; jadwal pemeriksaan telah dibuat.'
        : result.status === 'menunggu_dokter'
          ? 'Persetujuan admin tercatat. Permohonan masih menunggu dokter.'
          : result.status === 'menunggu_admin'
            ? 'Persetujuan dokter tercatat. Permohonan masih menunggu admin.'
            : 'Permohonan ditolak.');
      setError('');
      await load();
      setTimeout(() => setNotice(''), 5000);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function uploadProfilePhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.currentTarget.files?.[0];
    if (!file) return;
    const input = e.currentTarget;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setError('Pilih foto JPEG, PNG, atau WebP.'); input.value = ''; return; }
    if (file.size > 2 * 1024 * 1024) { setError('Ukuran foto maksimal 2 MB.'); input.value = ''; return; }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const dataUrl = String(reader.result || '');
        const response = await fetch('/api/me/profile-photo', { method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ content_type: file.type, data: dataUrl.split(',')[1] }) });
        const result = await response.json().catch(() => null);
        if (!response.ok) throw new Error(result?.detail || 'Foto profil gagal disimpan.');
        setMyProfile((prev) => ({ ...(prev || {}), photo_data_url: dataUrl }));
        setNotice('Foto profil berhasil diperbarui.'); setError('');
      } catch (err) { setError((err as Error).message); }
      input.value = '';
    };
    reader.onerror = () => setError('File foto tidak dapat dibaca.');
    reader.readAsDataURL(file);
  }

  function updateUserPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!passwordUser) return;
    const form = e.currentTarget;
    const data = new FormData(form);
    const password = String(data.get('password') || '');
    const confirmation = String(data.get('confirm_password') || '');
    if (password.length < 8) { setPasswordError('Kata sandi harus minimal 8 karakter.'); return; }
    if (password !== confirmation) { setPasswordError('Konfirmasi kata sandi belum cocok.'); return; }
    const target = passwordUser;
    setPasswordError('');
    void run(() => api(`/users/${target.id}/password`, 'PUT', { password }), `Kata sandi ${target.username} berhasil diperbarui.`);
    (document.getElementById('password-dialog') as HTMLDialogElement)?.close();
    form.reset();
    setPasswordUser(null);
  }

  async function downloadFhir(scope: 'summary' | 'full') {
    if (!selected?.id) return;
    try {
      const bundle = await api(`/records/${selected.id}/fhir?scope=${scope}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/fhir+json' }));
      const link = document.createElement('a'); link.href = url; link.download = `medichain-${selected.pseudo_id}-${scope}.fhir.json`;
      link.click(); URL.revokeObjectURL(url);
      setNotice(`Ekspor FHIR ${scope} berhasil diunduh.`);
    } catch (err) { setError((err as Error).message); }
  }

  async function downloadDiagnosisPdf() {
    if (!selected?.id) return;
    try {
      const response = await fetch(`/api/records/${selected.id}/diagnosis.pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `Gagal membuat PDF (${response.status})`);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `MediChain-Diagnosis-${selected.pseudo_id || selected.id}.pdf`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('PDF diagnosis berhasil diunduh.'); setError('');
    } catch (err) { setError((err as Error).message); }
  }

  if (!authReady) return <main className="min-h-screen grid grid-cols-[minmax(420px,48%)_1fr] bg-white max-[700px]:grid-cols-1"><section className="login-card"><div className="brand"><b>MediChain</b></div><h1>Memulihkan sesi…</h1><p className="muted">Memuat kembali ruang kerja Anda.</p></section></main>;
  if (!token) {
    const title = authMode === 'onboarding' ? 'Lengkapi profil pasien' : authMode === 'register' ? 'Buat akun pasien' : authMode === 'registered' ? 'Pendaftaran diterima' : 'Selamat datang kembali';
    const subtitle = authMode === 'onboarding' ? 'Beberapa informasi diperlukan untuk membuat rekam medis pasien.' : authMode === 'register' ? 'Isi data Anda. Akun akan aktif setelah disetujui admin atau auditor.' : authMode === 'registered' ? 'Akun Anda sedang menunggu persetujuan.' : 'Masuk ke ruang kerja klinis dan administrasi Anda.';
    return <main className="min-h-screen grid grid-cols-[minmax(420px,48%)_1fr] bg-white max-[700px]:grid-cols-1"><section className="login-card"><div className="brand"><div className="brand-icon">+</div><div><b>MediChain</b><span>Ruang layanan kesehatan</span></div></div><p className="eyebrow">AKSES AMAN ? LAYANAN TERHUBUNG</p><h1>{title}</h1><p className="muted">{subtitle}</p>
      {authMode === 'login' && <form onSubmit={login} className="form-stack"><label>Username<input name="username" autoComplete="username" required minLength={3} maxLength={40} placeholder="Masukkan username" /></label><label>Password<input name="password" autoComplete="current-password" type="password" required minLength={8} placeholder="Masukkan password" /></label>{error && <div className="alert">{error}</div>}<button className="primary full" disabled={busy || authBusy}>{busy || authBusy ? 'Memproses...' : 'Masuk ke MediChain'} <span>&rarr;</span></button><button type="button" className="auth-link-button" onClick={() => { setError(''); setAuthMode('register'); }}>Belum punya akun? <b>Buat akun pasien</b></button></form>}
      {authMode === 'register' && <form onSubmit={registerPatient} className="form-stack"><label>Nama lengkap<input name="full_name" autoComplete="name" required minLength={2} maxLength={120} placeholder="Nama sesuai identitas" /></label><label>Username<input name="username" autoComplete="username" required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.-]+" title="Gunakan huruf, angka, titik, garis bawah, atau tanda hubung." placeholder="contoh: siti.rahma" /></label><label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="nama@email.com" /></label><div className="form-grid"><label>Tanggal lahir<input name="birth_date" type="date" required max={new Date().toISOString().slice(0, 10)} /></label><label>Jenis kelamin<select name="sex" required defaultValue=""><option value="" disabled>Pilih</option><option value="L">Laki-laki</option><option value="P">Perempuan</option></select></label></div><label>Kata sandi<input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} aria-describedby="signup-password-help" placeholder="Minimal 10 karakter" /><small id="signup-password-help">Gunakan huruf besar, huruf kecil, dan angka.</small></label><label>Konfirmasi kata sandi<input name="confirm_password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} placeholder="Ulangi kata sandi" /></label>{error && <div className="alert">{error}</div>}<button className="primary full" disabled={authBusy}>{authBusy ? 'Mengirim pendaftaran…' : 'Daftar sebagai pasien'}</button><button type="button" className="auth-link-button" onClick={() => { setError(''); setAuthMode('login'); }}>Sudah punya akun? <b>Kembali masuk</b></button></form>}
      {authMode === 'registered' && <div className="form-stack"><div className="registration-confirmation" role="status"><span aria-hidden="true">✓</span><div><b>Pendaftaran berhasil dikirim</b><p>{pendingRegistrationUsername ? `Username: ${pendingRegistrationUsername}. ` : ''}Admin atau auditor perlu meninjau dan menyetujui akun Anda. Anda belum dapat masuk atau melihat rekam medis sebelum akun diaktifkan.</p></div></div><button type="button" className="primary full" onClick={() => { setError(''); setAuthMode('login'); }}>Kembali ke halaman masuk</button></div>}
      {authMode === 'onboarding' && <form onSubmit={finishGoogleRegistration} className="form-stack"><label>Tanggal lahir<input name="birth_date" type="date" required max={new Date().toISOString().slice(0, 10)} /></label><label>Jenis kelamin<select name="sex" required defaultValue=""><option value="" disabled>Pilih</option><option value="L">Laki-laki</option><option value="P">Perempuan</option></select></label><label>Nomor telepon<input name="phone" autoComplete="tel" required maxLength={30} placeholder="08?" /></label><label>Alamat<input name="address" autoComplete="street-address" required maxLength={1000} placeholder="Alamat domisili" /></label>{error && <div className="alert">{error}</div>}<button className="primary full" disabled={authBusy}>{authBusy ? 'Menyimpan?' : 'Selesaikan pendaftaran'}</button></form>}
      {authMode === 'login' && process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && <div className="google-auth-wrap"><div className="auth-divider"><span>atau lanjutkan dengan</span></div><div id="google-signin-button" className="google-signin-button"/></div>}
      <div className="secure-note"><span className="secure-dot"/> Koneksi dan data dilindungi</div></section><aside className="login-art"><div className="art-glow"/><div className="art-copy"><span className="eyebrow light">SATU RUANG UNTUK PERAWATAN YANG LEBIH BAIK</span><h2>Informasi tepat.<br/>Perawatan terarah.</h2><p>Hubungkan tim klinis, jadwal perawatan, dan layanan pasien dalam satu pengalaman yang aman.</p><div className="art-stat"><span className="pulse-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M2 12h4l3-8 5 16 3-8h5"/></svg></span><span><b>Terhubung sepanjang perjalanan</b><small>Informasi layanan tersaji untuk peran yang tepat</small></span></div></div><div className="art-orbit orbit-one"/><div className="art-orbit orbit-two"/></aside></main>;
  }

  const nav = navByRole[role].filter((item) => item !== 'ECG' || records.some((r) => r.ecg_available));
  const title = view;
  const rowsForPatient = filtered;
  const patientOptions = records.map((r) => <option key={r.id} value={r.id}>{r.patient_name}</option>);

  function table(headers: string[], cells: (r: Row) => React.ReactNode) {
    const hasDedicatedSearch = ['Pasien', 'Tracking'].includes(view);
    return <>{!hasDedicatedSearch && <div className="table-toolbar"><label className="search"><svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Cari ${view.toLocaleLowerCase()}…`} aria-label={`Cari ${view.toLocaleLowerCase()}`}/></label><span className="result-count">{rowsForPatient.length} dari {rows.length} data</span></div>}<div className="table-wrap"><table><thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead><tbody>{rowsForPatient.map((r, i) => <tr key={r.id || i}>{cells(r)}</tr>)}{!rowsForPatient.length && <tr><td className="empty-cell" colSpan={headers.length}>{dataLoading ? <span className="loading-inline"><i/>Memuat data…</span> : query ? 'Tidak ada data yang cocok dengan pencarian.' : 'Belum ada data untuk ditampilkan.'}</td></tr>}</tbody></table></div></>;
  }

  function careEditor(r: Row) {
    return <div className="inline-form"><select defaultValue={r.status || 'rawat_jalan'} id={`status-${r.patient_id || r.id}`}><option value="dirawat">Sedang dirawat</option><option value="operasi">Menjalani operasi</option><option value="rawat_jalan">Rawat jalan</option><option value="pemulihan">Masa pemulihan</option><option value="pulang">Sudah pulang</option></select><input defaultValue={r.room || ''} id={`room-${r.patient_id || r.id}`} placeholder="Contoh: Ruang Melati 204"/><button className="small primary" onClick={() => { const id = r.patient_id || r.id; void run(() => api(`/care/${id}`, 'PUT', { status: (document.getElementById(`status-${id}`) as HTMLSelectElement).value, room: (document.getElementById(`room-${id}`) as HTMLInputElement).value, note: '' }), 'Status perawatan diperbarui.'); }}>Simpan</button></div>;
  }

  function ecgPatientSearch(options: Row[], current: Row) {
    const normalizedSearch = ecgSearchQuery.trim().toLocaleLowerCase();
    const matches = options.filter((patient) => `${patient.patient_name || ''} ${patient.pseudo_id || ''}`.toLocaleLowerCase().includes(normalizedSearch));
    return <div className="ecg-patient-search"><label htmlFor="ecg-patient-search">Pilih pasien ECG</label><div className="ecg-search-box"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input id="ecg-patient-search" role="combobox" aria-autocomplete="list" aria-expanded={ecgSearchOpen} aria-controls="ecg-patient-results" value={ecgSearchOpen ? ecgSearchQuery : ecgSearchQuery || current.patient_name || ''} placeholder="Cari nama pasien…" onFocus={() => { if (!ecgSearchQuery || ecgSearchQuery === current.patient_name) setEcgSearchQuery(''); setEcgSearchOpen(true); }} onChange={(e) => { setEcgSearchQuery(e.target.value); setEcgSearchOpen(true); }} onKeyDown={(e) => { if (e.key === 'Escape') setEcgSearchOpen(false); }}/></div>{ecgSearchOpen && <div className="ecg-search-results" id="ecg-patient-results" role="listbox">{matches.length ? matches.map((patient) => <button type="button" role="option" aria-selected={patient.id === current.id} className="ecg-search-option" key={patient.id} onClick={() => { if (patient.id !== current.id) { setSelected(patient); setEcg(null); } setEcgSearchQuery(patient.patient_name || ''); setEcgSearchOpen(false); }}><span className="ecg-option-avatar">{patient.patient_name?.slice(0, 1) || 'P'}</span><span><b>{patient.patient_name}</b><small>{patient.room || 'Ruangan belum ditentukan'} · {patient.care_status === 'operasi' || patient.care_status === 'pemulihan' ? 'Pascaoperasi' : 'Rawat inap'}</small></span>{patient.id === current.id && <span className="ecg-option-selected" aria-label="Pasien terpilih">✓</span>}</button>) : <p className="ecg-search-empty">Pasien tidak ditemukan.</p>}</div>}</div>;
  }

  function content() {
    if (view === 'Terapi & pemeriksaan') {
      const canWrite = role === 'dokter' && !!selected?.can_edit;
      const reloadClinicalCare = async () => setClinicalCare(await api(`/records/${selected?.id}/clinical`));
      const saveCareForm = (e: FormEvent<HTMLFormElement>, path: string, message: string) => {
        e.preventDefault();
        const form = e.currentTarget;
        const body = Object.fromEntries(new FormData(form).entries());
        void run(async () => { const saved = await api(`/records/${selected?.id}/${path}`, 'POST', body); await reloadClinicalCare(); return saved; }, message);
        form.reset();
      };
      return <><div className="section-head"><div><h3>Terapi dan pemeriksaan penunjang</h3><p>Riwayat alergi, instruksi terapi, serta permintaan laboratorium dan radiologi.</p></div><label className="clinical-patient-select">Pasien<select value={selected?.id || ''} onChange={(e) => { const patient = records.find((item) => item.id === e.target.value); if (patient) setSelected(patient); }} aria-label="Pilih pasien">{patientOptions}</select></label></div>
        {!selected && <div className="notice-card">Belum ada pasien yang dapat ditampilkan.</div>}
        {selected && <><div className="care-summary-strip"><b>{selected.patient_name}</b><span>{selected.room || 'Ruangan belum ditentukan'}</span><span className={`pill ${selected.care_status || 'rawat_jalan'}`}>{statusName(selected.care_status)}</span></div>
          <div className="clinical-care-grid">
            <section className="innovation-card"><div className="clinical-card-title"><div><h3>Alergi</h3><p>Informasi penting sebelum pemberian terapi.</p></div><span>{clinicalCare?.allergies?.length || 0}</span></div>{canWrite && <form className="clinical-entry-form" onSubmit={(e) => saveCareForm(e, 'allergies', 'Alergi dicatat.')}><input name="substance" required placeholder="Zat atau obat"/><input name="reaction" placeholder="Reaksi yang pernah terjadi"/><select name="severity" defaultValue="unknown"><option value="unknown">Tingkat belum diketahui</option><option value="ringan">Ringan</option><option value="sedang">Sedang</option><option value="berat">Berat</option></select><button className="primary">Tambah alergi</button></form>}<div className="clinical-list">{(clinicalCare?.allergies || []).map((item: Row) => <article key={item.id}><div><b>{item.substance}</b><p>{item.reaction || 'Reaksi belum dicatat'}</p><small>{item.severity} · {item.status === 'active' ? 'Aktif' : 'Selesai'} · {item.recorded_by}</small></div>{canWrite && <button className="small ghost" onClick={() => void run(async () => { const saved = await api(`/records/${selected.id}/allergies/${item.id}`, 'PUT', { substance: item.substance, reaction: item.reaction, severity: item.severity, status: item.status === 'active' ? 'resolved' : 'active' }); await reloadClinicalCare(); return saved; }, 'Status alergi diperbarui.')}>{item.status === 'active' ? 'Tandai selesai' : 'Aktifkan'}</button>}</article>)}{!clinicalCare?.allergies?.length && <div className="empty-inline">Belum ada alergi yang tercatat.</div>}</div></section>
            <section className="innovation-card"><div className="clinical-card-title"><div><h3>Instruksi terapi</h3><p>Obat dan aturan pakai yang ditulis dokter.</p></div><span>{clinicalCare?.medications?.length || 0}</span></div>{canWrite && <form className="clinical-entry-form" onSubmit={(e) => saveCareForm(e, 'medications', 'Instruksi terapi disimpan.')}><input name="medication" required placeholder="Nama obat"/><input name="dose" required placeholder="Dosis, contoh: 500 mg"/><input name="route" required placeholder="Rute pemberian"/><input name="frequency" required placeholder="Frekuensi, contoh: 2 kali sehari"/><input name="instructions" placeholder="Catatan penggunaan"/><button className="primary">Tambah terapi</button></form>}<div className="clinical-list">{(clinicalCare?.medications || []).map((item: Row) => <article key={item.id}><div><b>{item.medication} · {item.dose}</b><p>{item.route} · {item.frequency}</p><small>{item.instructions || 'Tanpa catatan tambahan'} · {item.status === 'active' ? 'Aktif' : item.status}</small></div>{canWrite && item.status === 'active' && <button className="small ghost" onClick={() => void run(async () => { const saved = await api(`/records/${selected.id}/medications/${item.id}`, 'PUT', { status: 'completed' }); await reloadClinicalCare(); return saved; }, 'Terapi ditandai selesai.')}>Tandai selesai</button>}</article>)}{!clinicalCare?.medications?.length && <div className="empty-inline">Belum ada instruksi terapi.</div>}</div></section>
            <section className="innovation-card clinical-wide"><div className="clinical-card-title"><div><h3>Pemeriksaan penunjang</h3><p>Permintaan laboratorium atau radiologi dan hasil yang tersedia.</p></div><span>{clinicalCare?.diagnostics?.length || 0}</span></div>{canWrite && <form className="clinical-entry-form diagnostic-entry" onSubmit={(e) => saveCareForm(e, 'diagnostics', 'Permintaan pemeriksaan dibuat.')}><select name="kind"><option value="lab">Laboratorium</option><option value="radiology">Radiologi</option></select><input name="test_name" required placeholder="Nama pemeriksaan"/><input name="clinical_note" placeholder="Catatan klinis untuk pemeriksaan"/><button className="primary">Buat permintaan</button></form>}<div className="clinical-list">{(clinicalCare?.diagnostics || []).map((item: Row) => <article className="diagnostic-item" key={item.id}><div><b>{item.test_name}</b><p>{item.kind === 'lab' ? 'Laboratorium' : 'Radiologi'} · {item.clinical_note || 'Tanpa catatan'}</p>{item.result && <small>Hasil: {item.result}</small>}</div>{canWrite ? <form className="diagnostic-update" onSubmit={(e) => { e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => { const saved = await api(`/records/${selected.id}/diagnostics/${item.id}`, 'PUT', { status: data.get('status'), result: data.get('result') }); await reloadClinicalCare(); return saved; }, 'Status pemeriksaan diperbarui.'); }}><select name="status" defaultValue={item.status}><option value="requested">Diminta</option><option value="collected">Sampel diambil</option><option value="completed">Selesai</option><option value="cancelled">Dibatalkan</option></select><input name="result" defaultValue={item.result} placeholder="Masukkan hasil pemeriksaan"/><button className="small primary">Simpan hasil</button></form> : <span className="pill neutral">{item.status}</span>}</article>)}{!clinicalCare?.diagnostics?.length && <div className="empty-inline">Belum ada pemeriksaan penunjang.</div>}</div></section>
          </div></>}
      </>;
    }
    if (view === 'Profil saya') return <><div className="section-head"><div><h3>Profil saya</h3><p>Informasi akun pribadi Anda.</p></div></div><article className="record-panel self-profile"><div className="self-profile-photo">{myProfile?.photo_data_url ? <img src={myProfile.photo_data_url} alt="Foto profil"/> : <span>{(myProfile?.full_name || username).slice(0, 1).toUpperCase()}</span>}</div><div className="self-profile-main"><span className="eyebrow">{roleName[role].toUpperCase()}</span><h3>{myProfile?.full_name || username}</h3><p>@{myProfile?.username || username}</p>{['admin', 'dokter', 'auditor'].includes(role) ? <label className="photo-upload">{myProfile?.photo_data_url ? 'Ganti foto profil' : 'Tambah foto profil'}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={uploadProfilePhoto}/><small>JPEG, PNG, atau WebP · maksimal 2 MB</small></label> : <small>Foto profil hanya dapat ditambahkan oleh admin, dokter, dan auditor.</small>}</div><span className="pill approved">{myProfile?.is_active ? 'Akun aktif' : 'Aktif'}</span></article><div className="record-grid self-profile-details">{[['Username', myProfile?.username], ['Nama lengkap', myProfile?.full_name], ['Tanggal lahir', myProfile?.birth_date], ['Jenis kelamin', myProfile?.sex === 'L' ? 'Laki-laki' : myProfile?.sex === 'P' ? 'Perempuan' : '—'], ['Spesialisasi', myProfile?.specialty], ['Email', myProfile?.email], ['Nomor telepon', myProfile?.phone], ['Alamat', myProfile?.address]].map(([label, value]) => <article className="record-panel" key={label}><span className="field-label">{label}</span><p>{value || 'Belum diisi'}</p></article>)}</div><div className="profile-session-actions"><div><b>Akhiri sesi</b><p>Keluar dari akun MediChain ini di perangkat Anda.</p></div><button type="button" className="logout-profile-button" onClick={logout}>Keluar dari akun</button></div></>;
    if (view === 'Ringkasan') return <><div className="welcome-banner"><div><span className="eyebrow light">RUANG KERJA {roleName[role].toUpperCase()}</span><h2>Halo, {username}</h2><p>Semua informasi penting untuk hari ini, tersaji dalam satu tempat.</p></div><div className="banner-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M10 2h4v7h7v4h-7v7h-4v-7H3V9h7z"/></svg></div></div><div className="stat-grid"><article className="stat-card"><span className="stat-icon blue" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM20 8v6M23 11h-6"/></svg></span><small>Pasien terhubung</small><strong>{records.length}</strong><span className="stat-foot">Rekam medis dalam akses Anda</span></article><article className="stat-card"><span className="stat-icon green" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M8 14h3"/></svg></span><small>Jadwal mendatang</small><strong>{upcomingCount}</strong><span className="stat-foot">Pemeriksaan terjadwal</span></article><article className="stat-card"><span className="stat-icon amber" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span><small>Perlu perhatian</small><strong>{pendingCount}</strong><span className="stat-foot">Permohonan menunggu keputusan</span></article></div><div className="section-head"><div><h3>Pasien dalam pemantauan</h3><p>Status layanan dan ruang perawatan terkini.</p></div><button className="text-button" onClick={() => setView(role === 'pasien' ? 'Jadwal' : 'Pasien')}>Lihat semua →</button></div>{table(['Nama pasien', 'Status perawatan', 'Ruangan', 'Integritas'], (r) => { const integrityLabels: Record<string, string> = { valid: 'Valid', modified: 'Perlu ditinjau', version_mismatch: 'Versi berbeda', not_registered: 'Hash belum tercatat', sync_pending: 'Menunggu sinkronisasi', unavailable: 'Tidak tersedia' }; const integrityClass = r.integrity_status === 'valid' ? 'approved' : ['modified', 'version_mismatch'].includes(r.integrity_status) ? 'ditolak' : 'neutral'; return <><td><b>{r.patient_name}</b><small className="subcell">{r.age} tahun · {r.sex === 'L' ? 'Laki-laki' : 'Perempuan'}</small></td><td><span className={`pill ${r.care_status || r.status || 'rawat_jalan'}`}>{statusName(r.care_status || r.status)}</span></td><td>{r.room || 'Belum ditentukan'}</td><td><span className={`pill ${integrityClass}`}>{integrityLabels[r.integrity_status] || 'Belum diverifikasi'}</span></td></>; })}</>;
    if (view === 'Pasien') return <><div className="section-head"><div><h3>Daftar pasien</h3><p>Cari dan pilih pasien untuk melihat informasi layanan.</p></div></div><div className="toolbar"><label className="search"><svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nama, ruangan, atau status…" /></label><span className="result-count">{filtered.length} pasien</span></div>{table(['Nama pasien', 'Umur', 'Jenis kelamin', 'Status perawatan', 'Ruangan', 'Dokter penanggung jawab', 'Detail'], (r) => <><td><b>{r.patient_name}</b><small className="subcell">{r.pseudo_id}</small></td><td>{r.age} tahun</td><td>{r.sex === 'L' ? 'Laki-laki' : 'Perempuan'}</td><td><span className={`pill ${r.care_status || 'rawat_jalan'}`}>{statusName(r.care_status)}</span></td><td>{r.room || 'Belum ditentukan'}</td><td>{r.doctor_name ? <>{r.doctor_name}<small className="subcell">{r.specialty}</small></> : '?'}</td><td><button className="text-button" onClick={() => { setSelected(r); setClinical(null); setCareTimeline(null); setClinicalAlerts([]); setObservations([]); setRecordShares([]); setCreatedShare(null); setRecordDetailOpen(true); setView('Rekam medis'); }}>Buka rekam →</button></td></>)}</>;
    if (view === 'Rekam medis') return <>{!recordDetailOpen ? <><div className="section-head"><div><h3>Daftar rekam medis</h3><p>Cari nama pasien, lalu pilih untuk membuka ringkasan klinisnya.</p></div><span className="result-count">{filteredRecords.length} pasien</span></div><div className="toolbar"><label className="search"><svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nama pasien?" aria-label="Cari nama pasien" /></label></div><div className="record-list">{filteredRecords.map((r) => <button type="button" className="record-list-item" key={r.id} onClick={() => { setSelected(r); setClinical(null); setCareTimeline(null); setClinicalAlerts([]); setObservations([]); setRecordShares([]); setCreatedShare(null); setRecordDetailOpen(true); }}><span className="patient-avatar">{r.patient_name?.slice(0,1) || 'P'}</span><span className="record-list-info"><b>{r.patient_name}</b><small>{r.age} tahun ? {r.sex === 'L' ? 'Laki-laki' : 'Perempuan'} ? {r.room || 'Ruangan belum ditentukan'}</small></span><span className={`pill ${r.care_status || 'rawat_jalan'}`}>{statusName(r.care_status)}</span><span className="record-list-arrow" aria-hidden="true">?</span></button>)}{!filteredRecords.length && <div className="empty-state">{query ? 'Tidak ada pasien yang cocok dengan pencarian.' : 'Belum ada data rekam medis.'}</div>}</div></> : <><div className="section-head record-detail-head"><div><h3>Rekam medis pasien</h3><p>Ringkasan klinis dan catatan pemeriksaan.</p></div><div className="record-detail-actions"><button type="button" className="small ghost" onClick={() => void downloadFhir('summary')}>Ekspor FHIR ringkasan</button><button type="button" className="small ghost" onClick={() => void downloadFhir('full')}>Ekspor FHIR lengkap</button><button type="button" className="small ghost" disabled={!clinical?.diagnosis?.trim() || ['belum ada diagnosis', 'belum diisi', 'belum ditentukan', 'unknown'].includes(clinical?.diagnosis?.trim().toLocaleLowerCase())} title={!clinical?.diagnosis?.trim() ? 'PDF tersedia setelah diagnosis dicatat.' : 'Unduh ringkasan diagnosis pasien.'} onClick={() => void downloadDiagnosisPdf()}>Cetak diagnosis PDF</button><button type="button" className="ghost" onClick={() => setRecordDetailOpen(false)}>Kembali ke daftar</button></div></div>{clinical && selected ? <><div className="record-banner"><div className="patient-avatar">{selected.patient_name?.slice(0,1) || 'P'}</div><div><span className="eyebrow">PROFIL PASIEN</span><h3>{selected.patient_name}</h3><p>{selected.age} tahun · {selected.sex === 'L' ? 'Laki-laki' : 'Perempuan'} · {selected.room || 'Ruangan belum ditentukan'}</p></div><span className={`pill ${selected.care_status || 'rawat_jalan'}`}>{statusName(selected.care_status)}</span></div><div className="record-grid"><article className="record-panel"><span className="field-label">Riwayat kesehatan</span>{role === 'dokter' && selected.can_edit ? <textarea value={recordDraft.history} onChange={(e) => setRecordDraft({ ...recordDraft, history: e.target.value })}/> : <p>{clinical.history || 'Belum ada catatan.'}</p>}</article><article className="record-panel"><span className="field-label">Diagnosis</span>{role === 'dokter' && selected.can_edit ? <textarea value={recordDraft.diagnosis} onChange={(e) => setRecordDraft({ ...recordDraft, diagnosis: e.target.value })}/> : <p>{clinical.diagnosis || 'Belum ada diagnosis.'}</p>}</article><article className="record-panel wide-panel"><span className="field-label">Catatan tindak lanjut</span>{role === 'dokter' && selected.can_edit ? <textarea value={recordDraft.notes} onChange={(e) => setRecordDraft({ ...recordDraft, notes: e.target.value })}/> : <p>{clinical.notes || 'Belum ada catatan.'}</p>}</article></div>{role === 'dokter' && selected.can_edit && <button className="primary" onClick={() => void run(async () => { await api(`/records/${selected.id}`, 'PUT', recordDraft); const next = await api(`/records/${selected.id}`); setClinical(next); }, 'Diagnosis dan catatan disimpan.')}>Simpan pembaruan klinis</button>}
      <section className="innovation-card"><div className="section-head"><div><h3>Peringatan berbasis aturan</h3><p>Pengingat alur kerja untuk ditinjau tenaga medis, bukan diagnosis.</p></div></div>{clinicalAlerts.length ? <div className="alert-list">{clinicalAlerts.map((alert) => <article className="clinical-alert" key={alert.id}><b>{alert.title}</b><p>{alert.reason}</p><small>{alert.action}</small></article>)}</div> : <div className="empty-inline">Tidak ada pengingat alur kerja saat ini.</div>}</section>
      <section className="innovation-card"><div className="section-head"><div><h3>Observasi tanda vital</h3><p>Nilai dicatat dokter. Sistem tidak menafsirkan angka sebagai diagnosis.</p></div></div>{role === 'dokter' && selected.can_edit && <form className="vitals-form" onSubmit={(e) => { e.preventDefault(); const form=e.currentTarget; const data=new FormData(form); const number=(key:string) => { const value=data.get(key); return value ? Number(value) : null; }; void run(async () => { const result=await api(`/records/${selected.id}/observations`, 'POST', { heart_rate:number('heart_rate'), spo2:number('spo2'), temperature_c:number('temperature_c'), systolic_bp:number('systolic_bp'), diastolic_bp:number('diastolic_bp'), note:data.get('note') }); form.reset(); return result; }, 'Observasi tanda vital dicatat.'); }}><label>Nadi / menit<input type="number" name="heart_rate" min="20" max="250"/></label><label>SpO2 / %<input type="number" name="spo2" min="50" max="100" step="0.1"/></label><label>Suhu / ?C<input type="number" name="temperature_c" min="30" max="45" step="0.1"/></label><label>Sistolik / mmHg<input type="number" name="systolic_bp" min="50" max="280"/></label><label>Diastolik / mmHg<input type="number" name="diastolic_bp" min="30" max="180"/></label><label className="vitals-note">Catatan<input name="note" maxLength={300}/></label><button className="primary">Catat observasi</button></form>}{observations.length ? <div className="observation-list">{observations.map((o) => <article className="observation-row" key={o.id}><b>{dateLabel(o.observed_at)}</b><span>{o.heart_rate != null ? `Nadi ${o.heart_rate}/menit` : ''}{o.spo2 != null ? ` ? SpO2 ${o.spo2}%` : ''}{o.temperature_c != null ? ` ? Suhu ${o.temperature_c}?C` : ''}{o.systolic_bp != null || o.diastolic_bp != null ? ` ? TD ${o.systolic_bp ?? '?'}/${o.diastolic_bp ?? '?'} mmHg` : ''}</span>{o.note && <small>{o.note}</small>}</article>)}</div> : <div className="empty-inline">Belum ada observasi tercatat.</div>}</section>
      <section className="innovation-card"><div className="section-head"><div><h3>Riwayat perawatan terverifikasi</h3><p>Hash snapshot dibandingkan dengan event anchor dan rantai audit.</p></div>{(role === 'admin' || role === 'auditor') && <button className="small ghost" onClick={() => void run(() => api(`/records/${selected.id}/timeline/anchor`, 'POST'), 'Snapshot riwayat dikirim ke blockchain.')}>Anchor riwayat</button>}</div><div className={`timeline-proof ${careTimeline?.anchor_status || 'unanchored'}`}><b>{careTimeline?.anchor_status === 'confirmed' ? 'Snapshot ter-anchor' : careTimeline?.anchor_status === 'pending' ? 'Menunggu konfirmasi blockchain' : 'Snapshot belum ter-anchor'}</b><span>{careTimeline?.network || 'Chain'} ? Audit {careTimeline?.audit_chain_intact ? 'utuh' : 'perlu ditinjau'}</span><code>{careTimeline?.fingerprint || 'Menyiapkan fingerprint?'}</code>{careTimeline?.explorer_tx_url && <a href={careTimeline.explorer_tx_url} target="_blank" rel="noreferrer">Buka transaksi blockchain</a>}</div>{careTimeline?.events?.length ? <div className="care-timeline">{careTimeline.events.map((event:Row) => <article key={event.id}><i/><div><b>{event.type}</b><p>{event.description}</p><small>{dateLabel(event.occurred_at)} ? {event.actor}{event.doctor_name ? ` ? ${event.doctor_name}` : ''}</small></div></article>)}</div> : <div className="empty-inline">Belum ada riwayat perawatan.</div>}</section>
      {role === 'pasien' && <section className="innovation-card"><div className="section-head"><div><h3>Bagikan rekam medis dengan izin</h3><p>Tautan hanya dapat dibuka sampai masa berlaku habis dan bisa dicabut kapan saja.</p></div></div><form className="share-create-form" onSubmit={(e) => { e.preventDefault(); const form=e.currentTarget; const data=new FormData(form); void run(async () => { const result=await api(`/records/${selected.id}/shares`, 'POST', { expires_minutes:Number(data.get('expires_minutes')), scope:data.get('scope'), purpose:data.get('purpose') }); setCreatedShare(result); form.reset(); return result; }, 'Tautan berbagi dibuat.'); }}><label>Masa berlaku<select name="expires_minutes" defaultValue="1440"><option value="60">1 jam</option><option value="1440">24 jam</option><option value="10080">7 hari</option></select></label><label>Isi yang dibagikan<select name="scope" defaultValue="summary"><option value="summary">Ringkasan</option><option value="full">Rekam lengkap</option></select></label><label className="share-purpose">Tujuan berbagi<input name="purpose" maxLength={160} placeholder="Contoh: konsultasi lanjutan"/></label><button className="primary">Buat tautan dan QR</button></form>{createdShare && <div className="share-created"><img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(createdShare.qr_svg)}`} alt="QR tautan rekam medis"/><div><b>Tautan rahasia dibuat</b><p>{createdShare.purpose || 'Akses rekam medis terbatas waktu'} ? berlaku sampai {dateLabel(createdShare.expires_at)}</p><code>{createdShare.share_url}</code><button type="button" className="small ghost" onClick={() => void navigator.clipboard.writeText(createdShare.share_url)}>Salin tautan</button></div></div>}<div className="share-history"><h4>Tautan yang pernah dibuat</h4>{recordShares.length ? recordShares.map((share) => <article className="share-history-row" key={share.id}><div><b>{share.purpose || (share.scope === 'full' ? 'Rekam lengkap' : 'Ringkasan')}</b><small>{share.revoked_at ? 'Dicabut' : new Date(share.expires_at) < new Date() ? 'Kedaluwarsa' : 'Aktif'} ? {share.access_count} kali dibuka ? berakhir {dateLabel(share.expires_at)}</small>{share.accesses?.slice(0,3).map((access:Row,index:number) => <small key={index}>Akses {dateLabel(access.accessed_at)} ? {access.outcome}</small>)}</div>{!share.revoked_at && new Date(share.expires_at) > new Date() && <button type="button" className="small ghost" onClick={() => void run(() => api(`/records/${selected.id}/shares/${share.id}`, 'DELETE'), 'Tautan berbagi dicabut.')}>Cabut akses</button>}</article>) : <div className="empty-inline">Belum ada tautan berbagi.</div>}</div></section>}
      </> : <div className="empty-state">Pilih pasien untuk membuka rekam medisnya.</div>}</>}</>;
    if (view === 'Tracking') return <><div className="section-head"><div><h3>Riwayat aktivitas pasien</h3><p>Perjalanan perawatan, tindakan, dokter penanggung jawab, dan waktu kejadian.</p></div></div><div className="toolbar"><label className="search"><svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nama pasien, dokter, atau aktivitas…" /></label><span className="result-count">{filtered.length} aktivitas</span></div>{table(['Waktu', 'Pasien', 'Aktivitas', 'Dokter penanggung jawab', 'Bidang', 'Dicatat oleh'], (r) => <><td>{dateLabel(r.occurred_at)}</td><td><b>{r.patient_name}</b></td><td>{r.description}</td><td>{r.doctor_name || '—'}</td><td>{r.specialty || '—'}</td><td>{r.actor}</td></>)}</>;
    if (view === 'ECG') {
      const eligible = records.filter((r) => r.ecg_available);
      const ecgPatient = eligible.find((r) => r.id === selected?.id) || eligible[0];
      if (!ecgPatient) return <><div className="section-head"><div><h3>Monitor elektrokardiogram</h3><p>ECG hanya tersedia selama rawat inap dan pemulihan pascaoperasi.</p></div></div><div className="notice-card">Belum ada pasien rawat inap atau pasien pascaoperasi yang dapat menampilkan ECG.</div></>;
      const samples: number[] = Array.isArray(ecg?.samples) && ecg.samples.length ? ecg.samples : simulatedEcg(String(ecgPatient.id));
      const path = samples.map((v, i) => `${i ? 'L' : 'M'} ${(i / Math.max(samples.length - 1, 1) * 1000).toFixed(1)} ${(59 - v * 34).toFixed(1)}`).join(' ');
      return <><div className="section-head ecg-section-head"><div><h3>Monitor elektrokardiogram</h3><p>Visualisasi sinyal ECG untuk pasien terpilih.</p></div>{ecgPatientSearch(eligible, ecgPatient)}</div><div className="ecg-card"><div className="ecg-meta"><div><span className="eyebrow">PEMANTAUAN PASIEN</span><h3>{ecgPatient.patient_name}</h3><p>{ecgPatient.care_status === 'operasi' || ecgPatient.care_status === 'pemulihan' ? 'Pasien pascaoperasi' : 'Pasien rawat inap'} ? {ecg?.fs || 250} sampel/detik</p></div><span className="ecg-live"><i/> LIVE SIMULATION</span></div><div className="ecg-screen"><svg viewBox="0 0 1000 120" preserveAspectRatio="none" aria-label="Visualisasi gelombang ECG"><path className="ecg-grid" d="M0 20H1000M0 40H1000M0 60H1000M0 80H1000M0 100H1000M50 0V120M100 0V120M150 0V120M200 0V120M250 0V120M300 0V120M350 0V120M400 0V120M450 0V120M500 0V120M550 0V120M600 0V120M650 0V120M700 0V120M750 0V120M800 0V120M850 0V120M900 0V120M950 0V120"/><g className="ecg-motion"><path className="ecg-wave" d={path}/><path className="ecg-wave" d={path} transform="translate(1000 0)"/><animateTransform attributeName="transform" attributeType="XML" type="translate" from="0 0" to="-1000 0" dur="8s" repeatCount="indefinite"/></g></svg></div><div className="ecg-foot"><span>II · {ecg?.fs || 250} Hz</span><span>Simulasi sintetis; bukan untuk diagnosis</span><span>Rentang 8 detik</span></div></div></>;
    }
    if (view === 'Integritas') return <><div className="section-head"><div><h3>Verifikasi integritas rekam</h3><p>Bandingkan data rekam medis dengan sidik jari yang tercatat. Verifikasi memeriksa status dan tidak menulis ulang data atau blockchain.</p></div>{(role === 'admin' || role === 'auditor') && <><button className="small ghost" onClick={() => void run(() => api('/chain/sync', 'POST'), 'Antrean blockchain diproses.')}>Sinkronkan transaksi</button><button className="primary" onClick={() => void run(async () => { for (const r of records) { const result = await api(`/records/${r.id}/verify`, 'POST'); setIntegrity((prev) => ({ ...(prev || {}), [r.id]: result })); } }, 'Pemeriksaan selesai. Status terbaru sudah dimuat.')}>Jalankan verifikasi</button></>}</div>{role !== 'admin' && role !== 'auditor' && <div className="notice-card">Mode baca saja. Admin atau auditor dapat menjalankan verifikasi integritas.</div>}{table(['Pasien', 'Status integritas', 'Versi rekam', 'Blockchain', 'Aksi'], (r) => { const s = integrity?.[r.id] || r; const statusLabel = s.status === 'sync_pending' ? 'Menunggu sinkronisasi' : s.status === 'version_mismatch' ? 'Versi DB/blockchain berbeda' : s.status === 'valid' ? 'Valid' : s.status === 'modified' ? 'Perlu ditinjau' : s.status === 'not_registered' ? 'Hash belum tercatat' : 'Belum diverifikasi'; return <><td><b>{r.patient_name}</b></td><td><span className={`pill ${s.status === 'valid' ? 'approved' : s.status === 'modified' ? 'ditolak' : 'pending'}`}>{statusLabel}</span></td><td><b>v{r.version ?? '—'}</b><small className="subcell">Blockchain: {s.onchain?.version ? `v${s.onchain.version}` : 'belum tercatat'}</small></td><td><small>{s.chain?.network || 'MockChain'}</small>{s.transaction_hash && <small className="subcell">{s.transaction_hash.slice(0, 12)}...</small>}{s.explorer_tx_url && <a className="small ghost" href={s.explorer_tx_url} target="_blank" rel="noreferrer">Lihat transaksi</a>}</td><td><button className="small ghost" onClick={() => void run(async () => { const result = await api(`/records/${r.id}/${role === 'admin' || role === 'auditor' ? 'verify' : 'integrity'}`, role === 'admin' || role === 'auditor' ? 'POST' : 'GET'); setIntegrity((prev) => ({ ...(prev || {}), [r.id]: result })); }, role === 'admin' || role === 'auditor' ? 'Pemeriksaan integritas selesai.' : 'Status integritas dimuat.')}>{role === 'admin' || role === 'auditor' ? 'Periksa ulang' : 'Lihat'}</button></td></>; })}</>;
    if (view === 'Perawatan') return <><div className="section-head"><div><h3>Status perawatan</h3><p>Informasi rawat pasien dan ruang perawatan saat ini.</p></div></div>{table(['Nama pasien', 'Kondisi layanan', 'Ruang perawatan', 'Dokter penanggung jawab', ...(role === 'admin' || role === 'dokter' ? ['Perbarui status'] : [])], (r) => <><td><b>{r.patient_name}</b></td><td><span className={`pill ${r.status || 'rawat_jalan'}`}>{statusName(r.status)}</span></td><td>{r.room || 'Belum ditentukan'}</td><td>{r.doctor_name ? `${r.doctor_name} ? ${r.specialty}` : '?'}</td>{(role === 'admin' || role === 'dokter') && <td>{careEditor(r)}</td>}</>)}</>;
    if (view === 'Jadwal') return <><div className="section-head"><div><h3>Jadwal pemeriksaan</h3><p>Atur jadwal kontrol dan pemeriksaan pasien.</p></div>{(role === 'admin' || role === 'dokter') && <button className="primary" onClick={() => { setEditingAppointment(null); (document.getElementById('appointment-dialog') as HTMLDialogElement).showModal(); }}>ï¼‹ Buat jadwal</button>}</div>{table(['Pasien', 'Tanggal & waktu', 'Jenis kunjungan', 'Ruangan', 'Status', ...(role === 'admin' || role === 'dokter' ? ['Aksi'] : [])], (r) => <><td><b>{r.patient_name}</b></td><td>{dateLabel(r.scheduled_at)}</td><td>{r.kind}</td><td>{r.room}</td><td><span className="pill neutral">{statusName(r.status)}</span></td>{(role === 'admin' || role === 'dokter') && <td><div className="actions"><button className="small ghost" onClick={() => { setEditingAppointment(r); (document.getElementById('appointment-dialog') as HTMLDialogElement).showModal(); }}>Edit</button><button className="small ghost" onClick={() => void run(() => api(`/appointments/${r.id}`, 'DELETE'), 'Jadwal dihapus.')}>Hapus</button></div></td>}</>)}</>;
    if (view === 'Ajukan pemeriksaan') return <><div className="request-card"><span className="eyebrow">PERMOHONAN PASIEN</span><h3>Ajukan tanggal pemeriksaan</h3><p>Pilih waktu yang sesuai. Jadwal akan dikonfirmasi setelah disetujui dokter dan admin.</p><form className="form-grid" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(() => api('/appointment-requests', 'POST', { requested_at: f.get('date'), kind: f.get('kind'), notes: f.get('notes') }), 'Permohonan terkirim untuk ditinjau.'); e.currentTarget.reset(); }}><label>Tanggal dan waktu<input required type="datetime-local" name="date" min={new Date().toISOString().slice(0, 16)} /></label><label>Jenis pemeriksaan<select name="kind"><option>Kontrol rutin</option><option>Pemeriksaan jantung</option><option>Konsultasi dokter</option><option>Pemeriksaan lanjutan</option></select></label><label className="wide">Catatan untuk tim medis<textarea name="notes" rows={3} placeholder="Jelaskan keluhan atau waktu yang perlu diperhatikan" /></label><button className="primary">Kirim permohonan <span>→</span></button></form></div><div className="section-head"><div><h3>Status permohonan saya</h3><p>Persetujuan dokter dan admin dibutuhkan sebelum jadwal terbit.</p></div></div>{table(['Tanggal yang diajukan', 'Jenis pemeriksaan', 'Status', 'Catatan'], (r) => <><td>{dateLabel(r.requested_at)}</td><td>{r.kind}</td><td><span className={`pill ${r.status}`}>{statusName(r.status)}</span></td><td>{r.decision_note || 'Menunggu peninjauan'}</td></>)}</>;
    if (view === 'Permohonan') return <><div className="section-head"><div><h3>Permohonan pemeriksaan</h3><p>Permohonan masuk perlu persetujuan dokter dan admin.</p></div></div>{table(['Pasien', 'Tanggal pilihan', 'Jenis pemeriksaan', 'Persetujuan', 'Tindakan'], (r) => { const approvedByMe = role === 'admin' ? !!r.admin_approved_by : role === 'dokter' ? !!r.doctor_approved_by : false; const waitingFor = r.status === 'menunggu_dokter' ? 'Menunggu persetujuan dokter' : 'Menunggu persetujuan admin'; return <><td><b>{r.patient_name}</b></td><td>{dateLabel(r.requested_at)}</td><td>{r.kind}<small className="subcell">{r.notes}</small></td><td><span className={`pill ${r.status}`}>{statusName(r.status)}</span><small className="subcell">Dokter {r.doctor_approved_by ? '✓' : '○'} · Admin {r.admin_approved_by ? '✓' : '○'}</small></td><td>{r.status !== 'disetujui' && r.status !== 'ditolak' && <div className="actions">{approvedByMe ? <small className="subcell">Persetujuan Anda tercatat. {waitingFor}.</small> : <button className="small primary" onClick={() => void decideAppointmentRequest(r.id, 'setujui')}>Setujui</button>}<button className="small ghost" onClick={() => void decideAppointmentRequest(r.id, 'tolak')}>Tolak</button></div>}</td></>; })}</>;
    if (view === 'Tagihan') {
      return <>
        <div className="section-head">
          <div><h3>Tagihan layanan</h3><p>Rincian biaya dan tanggal jatuh tempo pasien.</p></div>
          {(role === 'admin' || role === 'auditor') && <button className="primary" onClick={() => { setEditingInvoice(null); (document.getElementById('invoice-dialog') as HTMLDialogElement).showModal(); }}>Buat tagihan</button>}
        </div>
        {table(['Pasien', 'Rincian', 'Jumlah', 'Jatuh tempo', 'Status', ...(role === 'pasien' ? ['Pembayaran'] : ((role === 'admin' || role === 'auditor') ? ['Aksi'] : []))], (r) => {
          const proofPending = r.payment_proof_status === 'pending';
          const proofRejected = r.payment_proof_status === 'rejected';
          const paymentLabel = r.status === 'lunas' ? 'Lunas' : proofPending ? 'Menunggu verifikasi' : proofRejected ? 'Bukti ditolak' : 'Belum lunas';
          const paymentClass = r.status === 'lunas' ? 'approved' : proofRejected ? 'ditolak' : 'pending';
          return <>
            <td><b>{r.patient_name}</b></td>
            <td>{r.description}</td>
            <td>{money(r.amount)}</td>
            <td>{r.due_date}</td>
            <td><span className={`pill ${paymentClass}`}>{paymentLabel}</span>{proofRejected && <small className="subcell">Alasan: {r.payment_proof_rejection_reason}</small>}</td>
            {(role === 'admin' || role === 'auditor') && <td><div className="actions">{role === 'admin' && proofPending && <button className="small primary" onClick={() => void openPaymentProof(r.payment_proof_id)}>Verifikasi bukti</button>}<button className="small ghost" onClick={() => { setEditingInvoice(r); (document.getElementById('invoice-dialog') as HTMLDialogElement).showModal(); }}>Edit</button><button className="small ghost" disabled={!!r.payment_proof_id} title={r.payment_proof_id ? 'Tagihan memiliki riwayat bukti pembayaran.' : undefined} onClick={() => void run(() => api(`/invoices/${r.id}`, 'DELETE'), 'Tagihan dihapus.')}>Hapus</button></div></td>}
            {role === 'pasien' && <td>{r.status === 'lunas'
              ? 'Sudah lunas'
              : proofPending
                ? <><span className="pill pending">Menunggu admin</span><small className="subcell">Bukti dikirim {dateLabel(r.payment_proof_submitted_at)}</small></>
                : <><button type="button" className="small primary" onClick={() => { setPayingInvoice(r); setQrisImageUnavailable(false); setPaymentProofDataUrl(''); setPaymentProofContentType(''); setPaymentProofFileName(''); setPaymentProofError(''); (document.getElementById('payment-dialog') as HTMLDialogElement).showModal(); }}>{proofRejected ? 'Unggah ulang' : 'Bayar'}</button>{proofRejected && <small className="subcell">Bukti sebelumnya ditolak. Periksa alasan di kolom status.</small>}</>}
            </td>}
          </>;
        })}
      </>;
    }
    if (view === 'Pengguna') return <><div className="section-head"><div><h3>Pengguna layanan</h3><p>Tinjau pendaftaran pasien, kelola akun, peran, profil, dan kredensial.</p></div><button className="primary" onClick={() => { setEditingUser(null); (document.getElementById('user-dialog') as HTMLDialogElement).showModal(); }}>＋ Tambah pengguna</button></div>{table(['Nama', 'Username', 'Peran', 'Status', 'Aksi'], (r) => <><td><b>{r.full_name}</b><small className="subcell">{r.email || r.phone || 'Profil pengguna'}</small></td><td>{r.username}</td><td><span className="pill neutral">{roleName[r.role as Role]}</span></td><td>{r.approval_status === 'menunggu_persetujuan' ? <span className="pill pending">Menunggu persetujuan</span> : r.is_active ? 'Aktif' : 'Nonaktif'}</td><td><div className="actions">{r.approval_status === 'menunggu_persetujuan' && <button className="small primary" onClick={() => { if (window.confirm(`Setujui akun pasien ${r.full_name}? Persetujuan akan membuat satu rekam medis awal dan mengaktifkan akses pasien.`)) void run(() => api(`/users/${r.id}/approve`, 'POST', {}), 'Akun pasien disetujui dan diaktifkan.'); }}>Tinjau &amp; aktifkan</button>}<button className="small ghost" onClick={() => { setEditingUser(r); (document.getElementById('user-dialog') as HTMLDialogElement).showModal(); }}>Edit profil</button><button className="small ghost" onClick={() => { setPasswordUser(r); setPasswordError(''); (document.getElementById('password-dialog') as HTMLDialogElement).showModal(); }}>Atur sandi</button><button className="small ghost" onClick={() => { const detail = r.role === 'pasien' ? `Hapus akun pasien ${r.full_name} beserta rekam medis, ECG, perawatan, jadwal, tagihan, dan aktivitas terkait? Hash blockchain dan audit historis tetap disimpan.` : `Hapus akun ${r.full_name}?`; if (window.confirm(detail)) void run(() => api(`/users/${r.id}`, 'DELETE'), 'Akun pengguna dihapus.'); }}>Hapus</button></div></td></>)}</>;
    if (view === 'Kontrol akses') return <><div className="section-head"><div><h3>Kontrol akses rekam medis</h3><p>Pengelolaan izin akses hanya tersedia untuk auditor.</p></div></div>{table(['Nama pasien', 'Dokter', 'Pasien', 'Auditor'], (r) => { const roles = r.roles || {}; return <><td><b>{r.name}</b></td>{['dokter','pasien','auditor'].map((key) => <td key={key}><label className="switch"><input type="checkbox" checked={!!roles[key]} onChange={(e) => void run(() => api(`/records/${r.id}/access/${key}`, 'PUT', { allowed: e.target.checked }), 'Izin akses diperbarui.')} /><span/></label><span className="switch-label">{roles[key] ? 'Diizinkan' : 'Dibatasi'}</span></td>)}</>; })}</>;
    if (view === 'Audit') return <><div className="section-head"><div><h3>Aktivitas terbaru</h3><p>Jejak aktivitas penggunaan layanan.</p></div></div>{table(['Waktu', 'Pengguna', 'Aktivitas', 'Hasil', 'Keterangan'], (r) => <><td>{dateLabel(r.ts)}</td><td>{r.actor}</td><td>{r.action}</td><td><span className="pill neutral">{r.outcome}</span></td><td>{r.detail}</td></>)}</>;
    return null;
  }

  function createAppointment(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget);
    const body = { patient_id: form.get('patient'), scheduled_at: form.get('date'), kind: form.get('kind'), room: form.get('room'), notes: '' };
    void run(() => editingAppointment ? api(`/appointments/${editingAppointment.id}`, 'PUT', body) : api('/appointments', 'POST', body), editingAppointment ? 'Jadwal diperbarui.' : 'Jadwal berhasil dibuat.');
    (document.getElementById('appointment-dialog') as HTMLDialogElement).close(); e.currentTarget.reset();
  }

  return <div className={`app-shell min-h-screen bg-canvas text-ink${theme === 'dark' ? ' theme-dark' : ''}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon">+</div><div><b>MediChain</b><span>Care workspace</span></div></div>
      <div className="workspace-label">RUANG KERJA</div>
      <nav>{nav.map((item) => <button key={item} className={view === item ? 'active' : ''} onClick={() => { setRows([]); setQuery(''); setView(item); }}><span className="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d={navIconPath[item] || navIconPath['Ringkasan']}/></svg></span>{item}</button>)}</nav>
      <div className="sidebar-bottom">
        <button className="profile" type="button" onClick={() => setView('Profil saya')}><span className="avatar">{myProfile?.photo_data_url ? <img src={myProfile.photo_data_url} alt=""/> : username.slice(0, 1).toUpperCase()}</span><span><b>{username}</b><small>{roleName[role]}</small></span></button>
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="topbar-title"><span className="crumb">MediChain <span>/</span> {view}</span><h1>{view}</h1><small>Ruang layanan kesehatan terpadu</small></div><div className="top-actions"><span className="live-status"><i/> Layanan aktif</span><button type="button" className="theme-toggle" onClick={toggleTheme} aria-label={`Ganti ke tema ${theme === 'dark' ? 'terang' : 'gelap'}`} title={`Ganti ke tema ${theme === 'dark' ? 'terang' : 'gelap'}`}><svg className="theme-toggle-icon" viewBox="0 0 24 24" aria-hidden="true">{theme === 'dark' ? <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></> : <path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/>}</svg><span className="theme-toggle-label">{theme === 'dark' ? 'Tema terang' : 'Tema gelap'}</span></button><button type="button" className="top-user" onClick={() => { setView('Profil saya'); setQuery(''); }} aria-label="Buka profil saya"><span className="top-avatar">{myProfile?.photo_data_url ? <img src={myProfile.photo_data_url} alt=""/> : username.slice(0, 1).toUpperCase()}</span><span className="top-user-copy"><b>{username}</b><small>{roleName[role]}</small></span></button></div></header>
      <section className="page-content">{error && <div className="alert page-alert">{error}<button type="button" onClick={() => setError('')}>×</button></div>}{notice && <div className="success page-alert">✓ &nbsp;{notice}</div>}{content()}</section>
      <footer className="footer"><span>© 2026 MediChain Health Systems</span><span>Privasi · Bantuan · Status sistem</span></footer>
    </main>
    <dialog id="appointment-dialog" className="dialog"><form onSubmit={createAppointment}><div className="dialog-head"><div><span className="eyebrow">JADWAL PEMERIKSAAN</span><h3>{editingAppointment ? 'Edit jadwal' : 'Buat jadwal pemeriksaan'}</h3></div><button type="button" className="icon-button" aria-label="Tutup" onClick={() => (document.getElementById('appointment-dialog') as HTMLDialogElement)?.close()}>×</button></div><label>Pasien<select name="patient" required disabled={!!editingAppointment} defaultValue={editingAppointment?.patient_id || records[0]?.id}>{patientOptions}</select></label><label>Tanggal dan waktu<input type="datetime-local" name="date" required defaultValue={editingAppointment?.scheduled_at?.slice(0, 16)} min={new Date().toISOString().slice(0, 16)}/></label><label>Jenis kunjungan<input name="kind" required defaultValue={editingAppointment?.kind || 'Kontrol rutin'}/></label><label>Ruangan<input name="room" defaultValue={editingAppointment?.room || 'Poli jantung'} required/></label><div className="dialog-actions"><button type="button" className="ghost" onClick={() => (document.getElementById('appointment-dialog') as HTMLDialogElement)?.close()}>Batal</button><button className="primary">Simpan jadwal</button></div></form></dialog>
    <dialog id="payment-dialog" className="dialog payment-dialog" onCancel={(e) => { if (paymentProofBusy) e.preventDefault(); }} onClose={() => {
      const fileInput = document.querySelector<HTMLInputElement>('#payment-dialog input[type="file"]');
      if (fileInput) fileInput.value = '';
      setPayingInvoice(null); setQrisImageUnavailable(false); setPaymentProofDataUrl('');
      setPaymentProofContentType(''); setPaymentProofFileName(''); setPaymentProofError('');
    }}>
      <form className="payment-dialog-content" onSubmit={submitPaymentProof}>
        <div className="dialog-head">
          <div><span className="eyebrow payment-eyebrow">PEMBAYARAN QRIS</span><h3>Bayar dengan GoPay atau QRIS</h3><p className="dialog-description">Pindai QRIS, selesaikan pembayaran, lalu unggah bukti transaksi.</p></div>
          <button type="button" className="icon-button" aria-label="Tutup pembayaran" disabled={paymentProofBusy} onClick={() => (document.getElementById('payment-dialog') as HTMLDialogElement).close()}>Tutup</button>
        </div>
        {payingInvoice && <>
          <div className="payment-summary"><span>Tagihan #{payingInvoice.id} - {payingInvoice.description}</span><strong>{money(payingInvoice.amount)}</strong><small>Jatuh tempo {payingInvoice.due_date}</small></div>
          <div className="qris-payment-layout">
            <div className="qris-frame">
              {qrisImageUnavailable
                ? <div className="qris-missing"><b>QRIS belum dipasang</b><span>Letakkan QRIS GoPay Merchant Anda sebagai <code>public/gopay-qris.png</code>, lalu muat ulang aplikasi.</span></div>
                : <img src={GOPAY_QRIS_IMAGE} alt="QRIS GoPay Merchant" onError={() => setQrisImageUnavailable(true)} />}
            </div>
            <div className="qris-instructions">
              <b>Cara membayar</b>
              <ol><li>Buka GoPay atau aplikasi bank/e-wallet yang mendukung QRIS.</li><li>Pindai QR di samping.</li><li>Masukkan nominal tepat seperti jumlah tagihan.</li><li>Pastikan nama merchant dan nominal benar sebelum membayar.</li></ol>
            </div>
          </div>
          <div className="payment-manual-notice"><b>Menunggu verifikasi admin</b><span>Setelah membayar, unggah gambar bukti. Tagihan tetap belum lunas sampai admin mencocokkan transaksi di GoPay Merchant dan menyetujui bukti.</span></div>
          <label className="proof-upload-label">Bukti pembayaran
            <input type="file" accept="image/jpeg,image/png,image/webp" required onChange={(e) => selectPaymentProof(e.currentTarget.files?.[0])}/>
            <small className="subcell">Format JPG, PNG, atau WebP. Maksimal 2 MB.</small>
          </label>
          {paymentProofFileName && <div className="proof-file-name">{paymentProofFileName}</div>}
          {paymentProofDataUrl && <img className="proof-preview" src={paymentProofDataUrl} alt="Pratinjau bukti pembayaran"/>}
          {paymentProofError && <div className="alert">{paymentProofError}</div>}
        </>}
        <div className="dialog-actions"><button type="button" className="ghost" disabled={paymentProofBusy} onClick={() => (document.getElementById('payment-dialog') as HTMLDialogElement).close()}>Batal</button><button type="submit" className="primary" disabled={paymentProofBusy}>{paymentProofBusy ? 'Mengirim…' : 'Kirim bukti & konfirmasi'}</button></div>
      </form>
    </dialog>
    <dialog id="payment-review-dialog" className="dialog proof-review-dialog" onClose={() => { setReviewingProof(null); setReviewProofError(''); setProofRejectReason(''); }}>
      {reviewingProof && <div className="payment-dialog-content">
        <div className="dialog-head"><div><span className="eyebrow payment-eyebrow">TINJAU BUKTI</span><h3>Verifikasi pembayaran</h3><p className="dialog-description">Periksa bukti dan cocokkan transaksi melalui GoPay Merchant sebelum menyetujui.</p></div><button type="button" className="icon-button" aria-label="Tutup tinjauan" onClick={() => (document.getElementById('payment-review-dialog') as HTMLDialogElement).close()}>Tutup</button></div>
        <div className="payment-summary"><span>{reviewingProof.patient_name} · Tagihan #{reviewingProof.invoice_id}</span><strong>{money(reviewingProof.amount)}</strong><small>{reviewingProof.description} · Dikirim {dateLabel(reviewingProof.submitted_at)}</small></div>
        <img className="proof-review-image" src={reviewingProof.image_data_url} alt={`Bukti pembayaran tagihan ${reviewingProof.invoice_id}`}/>
        <label>Alasan penolakan (wajib jika menolak)<textarea className="proof-reject-reason" value={proofRejectReason} maxLength={500} onChange={(e) => setProofRejectReason(e.currentTarget.value)} placeholder="Contoh: nominal atau transaksi tidak cocok dengan riwayat GoPay Merchant."/></label>
        {reviewProofError && <div className="alert">{reviewProofError}</div>}
        <div className="dialog-actions"><button type="button" className="ghost" disabled={reviewProofBusy} onClick={() => (document.getElementById('payment-review-dialog') as HTMLDialogElement).close()}>Tutup</button><button type="button" className="ghost" disabled={reviewProofBusy} onClick={() => void reviewPaymentProof('reject')}>{reviewProofBusy ? 'Memproses…' : 'Tolak bukti'}</button><button type="button" className="primary" disabled={reviewProofBusy} onClick={() => void reviewPaymentProof('approve')}>{reviewProofBusy ? 'Memproses…' : 'Setujui & tandai lunas'}</button></div>
      </div>}
    </dialog>
    <dialog id="invoice-dialog" className="dialog"><form onSubmit={(e) => { e.preventDefault(); const form = e.currentTarget; const data = new FormData(form); const body: Row = { description: data.get('description'), amount: data.get('amount') ?? editingInvoice?.amount, due_date: data.get('due_date') }; void run(() => api(editingInvoice ? `/invoices/${editingInvoice.id}` : '/invoices', editingInvoice ? 'PUT' : 'POST', editingInvoice ? body : { ...body, patient_id: data.get('patient') }), editingInvoice ? 'Tagihan diperbarui.' : 'Tagihan diterbitkan.'); (document.getElementById('invoice-dialog') as HTMLDialogElement)?.close(); form.reset(); }}><div className="dialog-head"><div><span className="eyebrow">ADMINISTRASI</span><h3>{editingInvoice ? 'Edit tagihan' : 'Buat tagihan'}</h3></div><button type="button" className="icon-button" aria-label="Tutup" onClick={() => (document.getElementById('invoice-dialog') as HTMLDialogElement)?.close()}>×</button></div>{!editingInvoice && <label>Pasien<select name="patient" required>{patientOptions}</select></label>}<label>Rincian tagihan<input name="description" required defaultValue={editingInvoice?.description || ''}/></label><label>Jumlah (IDR)<input name="amount" type="number" min="1" step="0.01" required disabled={!!editingInvoice && (editingInvoice.payment_proof_status === 'pending' || editingInvoice.status === 'lunas')} defaultValue={editingInvoice?.amount || ''}/>{editingInvoice?.payment_proof_status === 'pending' && <small className="subcell">Jumlah tidak dapat diubah selama bukti pembayaran menunggu verifikasi.</small>}{editingInvoice?.status === 'lunas' && <small className="subcell">Jumlah tagihan lunas tidak dapat diubah.</small>}</label><label>Jatuh tempo<input name="due_date" type="date" required defaultValue={editingInvoice?.due_date || ''}/></label>{editingInvoice && <small className="subcell">Status lunas hanya berubah setelah admin menyetujui bukti pembayaran.</small>}<div className="dialog-actions"><button type="button" className="ghost" onClick={() => (document.getElementById('invoice-dialog') as HTMLDialogElement)?.close()}>Batal</button><button className="primary">Simpan tagihan</button></div></form></dialog>
    <dialog id="user-dialog" className="dialog"><form key={editingUser?.id ?? 'new-user'} onSubmit={(e) => { e.preventDefault(); const form = e.currentTarget; const d = new FormData(form); const body: Row = Object.fromEntries(d.entries()); if (body.is_active !== undefined) body.is_active = body.is_active === 'true'; if (!body.birth_date) delete body.birth_date; if (!body.sex) delete body.sex; if (editingUser) delete body.password; void run(() => api(editingUser ? `/users/${editingUser.id}` : '/users', editingUser ? 'PUT' : 'POST', body), editingUser ? 'Profil pengguna diperbarui.' : 'Pengguna berhasil ditambahkan.'); (document.getElementById('user-dialog') as HTMLDialogElement)?.close(); form.reset(); }}><div className="dialog-head"><div><span className="eyebrow">{editingUser ? 'PROFIL PENGGUNA' : 'AKUN BARU'}</span><h3>{editingUser ? 'Edit pengguna layanan' : 'Tambah pengguna layanan'}</h3></div><button type="button" className="icon-button" aria-label="Tutup" onClick={() => (document.getElementById('user-dialog') as HTMLDialogElement)?.close()}>×</button></div><label>Nama lengkap<input name="full_name" required minLength={2} defaultValue={editingUser?.full_name || ''} onChange={(e) => { if (editingUser) return; const input = e.currentTarget.form?.elements.namedItem('username') as HTMLInputElement | null; if (input && (!input.value || input.value === input.dataset.autoValue)) { const suggestion = usernameSuggestion(e.currentTarget.value).slice(0, 40); input.value = suggestion; input.dataset.autoValue = suggestion; } }}/></label><label>Username<input name="username" required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.-]+" placeholder="contoh: bima.setiawan" defaultValue={editingUser?.username || ''}/></label>{!editingUser && <label>Kata sandi awal<input name="password" type="password" required minLength={8}/></label>}<label>Peran<select name="role" defaultValue={editingUser?.role || 'pasien'}><option value="pasien">Pasien</option><option value="dokter">Dokter</option><option value="admin">Admin</option><option value="auditor">Auditor</option></select></label><label>Spesialisasi dokter<select name="specialty" defaultValue={editingUser?.specialty || 'Penyakit Dalam'}>{['Penyakit Dalam', 'Jantung', 'Bedah', 'Saraf', 'Ortopedi', 'Anak', 'Paru', 'Kebidanan'].map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Tanggal lahir<input name="birth_date" type="date" defaultValue={editingUser?.birth_date || ''}/></label><label>Jenis kelamin<select name="sex" defaultValue={editingUser?.sex || ''}><option value="">Pilih</option><option value="L">Laki-laki</option><option value="P">Perempuan</option></select></label><label>Alamat<input name="address" defaultValue={editingUser?.address || ''}/></label><label>Nomor telepon<input name="phone" defaultValue={editingUser?.phone || ''}/></label><label>Email<input name="email" type="email" defaultValue={editingUser?.email || ''}/></label>{editingUser && <label>Status akun<select name="is_active" defaultValue={editingUser.is_active ? 'true' : 'false'}><option value="true">Aktif</option><option value="false">Nonaktif</option></select></label>}<div className="dialog-actions"><button type="button" className="ghost" onClick={() => (document.getElementById('user-dialog') as HTMLDialogElement)?.close()}>Batal</button><button className="primary">{editingUser ? 'Simpan perubahan' : 'Buat akun'}</button></div></form></dialog>

    <dialog id="password-dialog" className="dialog"><form key={passwordUser?.id ?? 'password-user'} onSubmit={updateUserPassword}><div className="dialog-head"><div><span className="eyebrow">KEAMANAN AKUN</span><h3>Atur kata sandi</h3><p className="dialog-description">Buat kata sandi baru untuk <b>{passwordUser?.username || 'pengguna'}</b>.</p></div><button type="button" className="icon-button" aria-label="Tutup" onClick={() => { (document.getElementById('password-dialog') as HTMLDialogElement)?.close(); setPasswordUser(null); }}>?</button></div>{passwordError && <div className="alert">{passwordError}</div>}<label>Kata sandi baru<input name="password" type="password" autoComplete="new-password" required minLength={8} placeholder="Minimal 8 karakter"/></label><label>Ulangi kata sandi<input name="confirm_password" type="password" autoComplete="new-password" required minLength={8} placeholder="Ketik ulang kata sandi"/></label><div className="dialog-actions"><button type="button" className="ghost" onClick={() => { (document.getElementById('password-dialog') as HTMLDialogElement)?.close(); setPasswordUser(null); }}>Batal</button><button className="primary">Simpan kata sandi</button></div></form></dialog>
  </div>;
}

function statusName(value?: string) {
  const labels: Record<string, string> = {dirawat:'Sedang dirawat', operasi:'Menjalani operasi', rawat_jalan:'Rawat jalan', pemulihan:'Masa pemulihan', pulang:'Sudah pulang', terjadwal:'Terjadwal', selesai:'Selesai', dibatalkan:'Dibatalkan', menunggu_dokter:'Menunggu dokter', menunggu_admin:'Menunggu admin', disetujui:'Disetujui', ditolak:'Ditolak'};
  return labels[value || ''] || value || 'Belum ditentukan';
}
