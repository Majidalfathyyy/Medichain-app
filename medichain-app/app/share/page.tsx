'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

type ShareData = {
  bundle: { entry?: Array<{ resource: Record<string, any> }> };
  integrity: { status: string; export_fingerprint: string; source_record_version: number; chain_network: string; chain_version?: number | null };
  purpose: string;
  expires_at: string;
};

function decodeBase64Utf8(value: string) {
  const binary = atob(value);
  return new TextDecoder().decode(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}

export default function SharedRecordPage() {
  const [data, setData] = useState<ShareData | null>(null);
  const [error, setError] = useState('Memeriksa tautan berbagi…');

  useEffect(() => {
    const token = window.location.hash.slice(1);
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    if (!token) { setError('Token berbagi tidak ditemukan. Buka tautan lengkap yang diberikan pasien.'); return; }
    void fetch('/api/share/access', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
    }).then(async (response) => {
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail || `Tautan tidak dapat dibuka (${response.status}).`);
      setData(payload); setError('');
    }).catch((cause) => setError(cause instanceof Error ? cause.message : 'Tautan tidak dapat dibuka.'));
  }, []);

  const resources = data?.bundle.entry?.map((entry) => entry.resource) || [];
  const patient = resources.find((item) => item.resourceType === 'Patient');
  const diagnosis = resources.filter((item) => item.resourceType === 'Condition');
  const encounter = resources.find((item) => item.resourceType === 'Encounter');
  const notes = resources.find((item) => item.resourceType === 'DocumentReference');
  const observations = resources.filter((item) => item.resourceType === 'Observation');
  const careEvents = resources.filter((item) => item.resourceType === 'Provenance');

  return <main className="shared-page"><header className="shared-header"><div className="brand"><div className="brand-icon">+</div><div><b>MediChain</b><span>Rekam medis yang dibagikan</span></div></div><span className="shared-secure">Tautan terbatas waktu</span></header>
    <section className="shared-content"><span className="eyebrow">AKSES DENGAN PERSETUJUAN PASIEN</span><h1>Ringkasan rekam medis</h1>
      {error && <div className="alert">{error}</div>}
      {data && <><div className="record-banner"><div className="patient-avatar">{patient?.name?.[0]?.text?.slice(0, 1) || 'P'}</div><div><span className="eyebrow">IDENTITAS PASIEN</span><h3>{patient?.name?.[0]?.text || 'Pasien'}</h3><p>ID {patient?.identifier?.[0]?.value || '—'} · Versi rekam v{data.integrity.source_record_version}</p></div><span className={`pill ${data.integrity.status === 'valid' ? 'approved' : 'pending'}`}>{data.integrity.status === 'valid' ? 'Integritas valid' : `Integritas: ${data.integrity.status}`}</span></div>
        <div className="shared-grid"><article className="record-panel"><span className="field-label">Diagnosis tercatat</span>{diagnosis.map((item) => <p key={item.id}>{item.code?.text}</p>)}</article><article className="record-panel"><span className="field-label">Status perawatan</span><p>{encounter?.status || 'Belum tercatat'}</p><small>{encounter?.location?.[0]?.location?.display || 'Lokasi tidak dicantumkan'}</small></article></div>
        {notes && <article className="record-panel shared-notes"><span className="field-label">Catatan tindak lanjut</span><p>{notes.content?.[0]?.attachment?.data ? decodeBase64Utf8(notes.content[0].attachment.data) : 'Tidak ada catatan.'}</p></article>}
        {!!observations.length && <article className="record-panel shared-notes"><span className="field-label">Observasi tanda vital</span>{observations.map((item) => <p key={item.id}>{new Date(item.effectiveDateTime).toLocaleString('id-ID')} · {item.component?.map((component: Record<string, any>) => `${component.code?.coding?.[0]?.display}: ${component.valueQuantity?.value} ${component.valueQuantity?.unit}`).join(' · ')}</p>)}</article>}
        {!!careEvents.length && <article className="record-panel shared-notes"><span className="field-label">Riwayat perawatan</span>{careEvents.map((item) => <p key={item.id}>{new Date(item.recorded).toLocaleString('id-ID')} · {item.activity?.text} · {item.agent?.[0]?.who?.display}</p>)}</article>}
        <article className="timeline-proof"><b>{data.integrity.status === 'valid' ? 'Sidik jari rekam cocok dengan catatan blockchain' : 'Status sidik jari perlu ditinjau'}</b><span>{data.integrity.chain_network}{data.integrity.chain_version ? ` · versi blockchain v${data.integrity.chain_version}` : ''}</span><code>Fingerprint ekspor: {data.integrity.export_fingerprint}</code></article>
        <p className="shared-purpose">Tujuan: {data.purpose || 'Tidak dicantumkan'} · Tautan berakhir {new Date(data.expires_at).toLocaleString('id-ID')}</p>
        <button className="small ghost" onClick={() => { const blob = new Blob([JSON.stringify(data.bundle, null, 2)], { type: 'application/fhir+json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `medichain-${patient?.id || 'rekam'}-shared.fhir.json`; a.click(); URL.revokeObjectURL(url); }}>Unduh FHIR JSON</button>
      </>}
      <footer className="shared-footer"><span>Bagikan hanya kepada tenaga kesehatan yang dituju.</span><Link href="/">MediChain</Link></footer>
    </section></main>;
}
