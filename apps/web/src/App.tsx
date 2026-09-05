import { useCallback, useEffect, useState } from 'react';

import './App.css';
import {
  fetchApplicationHealth,
  fetchCacheHealth,
  fetchDatabaseHealth,
  type DependencyState,
} from './api/client';

/*
 * Phase 0 verification page.
 *
 * This is a technical check screen, not the start of the platform UI.
 * Its labels are intentionally temporary: from Phase 1 every visible string
 * comes from the central i18n layer and no text is hard-coded in a component.
 */

type ProbeState = DependencyState | 'loading' | 'error';

interface Probe {
  key: string;
  label: string;
  state: ProbeState;
  detail: string | null;
}

const INITIAL_PROBES: Probe[] = [
  { key: 'app', label: 'التطبيق', state: 'loading', detail: null },
  { key: 'db', label: 'قاعدة البيانات (PostgreSQL)', state: 'loading', detail: null },
  { key: 'cache', label: 'الذاكرة المؤقتة (Redis)', state: 'loading', detail: null },
];

const STATE_LABELS: Record<ProbeState, string> = {
  loading: 'جارٍ الفحص…',
  up: 'يعمل',
  down: 'غير متاح',
  disabled: 'غير مفعّل في هذه المرحلة',
  error: 'تعذر الوصول',
};

function stateClass(state: ProbeState): string {
  if (state === 'up') return 'state state--up';
  if (state === 'down' || state === 'error') return 'state state--down';
  if (state === 'disabled') return 'state state--disabled';
  return 'state';
}

export default function App() {
  const [probes, setProbes] = useState<Probe[]>(INITIAL_PROBES);
  const [checking, setChecking] = useState(false);

  const runChecks = useCallback(async () => {
    setChecking(true);
    setProbes(INITIAL_PROBES);

    const [app, database, cache] = await Promise.all([
      fetchApplicationHealth().then(
        (value) => ({ state: 'up' as ProbeState, detail: `${value.name} · ${value.version}` }),
        () => ({ state: 'error' as ProbeState, detail: null }),
      ),
      fetchDatabaseHealth().then(
        (value) => ({ state: value.status as ProbeState, detail: value.detail }),
        () => ({ state: 'error' as ProbeState, detail: null }),
      ),
      fetchCacheHealth().then(
        (value) => ({ state: value.status as ProbeState, detail: value.detail }),
        () => ({ state: 'error' as ProbeState, detail: null }),
      ),
    ]);

    setProbes([
      { key: 'app', label: 'التطبيق', state: app.state, detail: app.detail },
      {
        key: 'db',
        label: 'قاعدة البيانات (PostgreSQL)',
        state: database.state,
        detail: database.detail,
      },
      {
        key: 'cache',
        label: 'الذاكرة المؤقتة (Redis)',
        state: cache.state,
        detail: cache.detail,
      },
    ]);
    setChecking(false);
  }, []);

  useEffect(() => {
    void runChecks();
  }, [runChecks]);

  return (
    <main className="page">
      <h1 className="page__title">منصة سهل المطور — فحص تقني</h1>
      <p className="page__note">
        صفحة تحقق مؤقتة للمرحلة الصفرية. واجهة المنصة تبدأ في المرحلة الأولى.
      </p>

      {probes.map((probe) => (
        <section className="card" key={probe.key}>
          <span className="card__label">{probe.label}</span>
          <span className={stateClass(probe.state)}>{STATE_LABELS[probe.state]}</span>
          {probe.detail ? <span className="card__detail">{probe.detail}</span> : null}
        </section>
      ))}

      <div className="actions">
        <button type="button" onClick={() => void runChecks()} disabled={checking}>
          إعادة الفحص
        </button>
      </div>
    </main>
  );
}
