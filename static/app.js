const state = { csrf: '', status: null, activity: null, metrics: null, metricRange: '24h', schedules: [], history: [], settings: {} };
const titles = {
  dashboard: ['대시보드', 'TrueNAS 전원과 서비스 상태를 확인합니다.'],
  resources: ['리소스 기록', '용량, 사용률, 처리량과 온도 변화를 확인합니다.'],
  schedules: ['예약 관리', 'NAS를 켜고 끄는 반복 일정을 관리합니다.'],
  history: ['실행 기록', '수동 및 예약 작업의 결과를 확인합니다.'],
  settings: ['설정', '네트워크와 보안 구성을 확인합니다.']
};

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '요청에 실패했습니다.');
  return data;
}

function showNotice(message, error = false) {
  const notice = document.querySelector('#notice');
  notice.textContent = message;
  notice.classList.toggle('error', error);
  notice.hidden = false;
  window.setTimeout(() => { notice.hidden = true; }, 5000);
}

function showPage(page) {
  document.querySelectorAll('.nav-item').forEach(button => button.classList.toggle('is-active', button.dataset.page === page));
  document.querySelectorAll('.page').forEach(panel => panel.classList.toggle('is-active', panel.dataset.pagePanel === page));
  document.querySelector('#page-title').textContent = titles[page][0];
  document.querySelector('#page-subtitle').textContent = titles[page][1];
}

function renderStatus() {
  const status = state.status;
  if (!status) return;
  const label = document.querySelector('#nas-status');
  label.className = `state ${status.online ? 'online' : 'offline'}`;
  label.textContent = status.ready ? '● 온라인 · 모든 서비스 준비됨' : status.online ? '● 온라인 · 일부 서비스 준비 중' : '○ 오프라인';
  Object.entries(status.checks).forEach(([name, ok]) => {
    const element = document.querySelector(`[data-check="${name}"]`);
    element.textContent = ok === null ? '사용 안 함' : ok ? '정상' : '응답 없음';
    element.className = ok === null ? '' : ok ? 'ok' : 'fail';
  });
  const progress = document.querySelector('#action-progress');
  progress.hidden = !status.action;
  if (status.action) document.querySelector('#action-message').textContent = status.action.message || '전원 작업 진행 중';
  document.querySelector('#wake-button').disabled = Boolean(status.action);
  document.querySelector('#wake-button').title = status.online ? 'NAS가 이미 온라인이면 별도 패킷을 보내지 않습니다.' : '';
  const shutdownButton = document.querySelector('#shutdown-button');
  shutdownButton.disabled = Boolean(status.action) || !status.online;
  shutdownButton.textContent = status.api_key_configured ? '안전하게 끄기' : '끄기 설정 필요';
  shutdownButton.title = status.api_key_configured ? '' : 'TrueNAS API 키를 등록해야 합니다.';
}

function formatRate(value) {
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let amount = Number(value) || 0;
  let unit = 0;
  while (amount >= 1000 && unit < units.length - 1) { amount /= 1000; unit += 1; }
  const digits = amount >= 100 || unit === 0 ? 0 : amount >= 10 ? 1 : 2;
  return `${amount.toFixed(digits)} ${units[unit]}`;
}

function formatBytes(value) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = Number(value) || 0;
  let unit = 0;
  while (amount >= 1000 && unit < units.length - 1) { amount /= 1000; unit += 1; }
  const digits = unit >= 3 ? 2 : amount >= 100 ? 0 : amount >= 10 ? 1 : 2;
  return `${amount.toFixed(digits)} ${units[unit]}`;
}

function percentage(value, total) {
  return total > 0 ? Math.max(0, Math.min(100, 100 * value / total)) : 0;
}

function renderResources() {
  const activity = state.activity;
  const available = activity?.available && state.status?.online;
  const pools = available ? (activity.pools || []) : [];
  const total = pools.reduce((sum, pool) => sum + (Number(pool.size) || 0), 0);
  const used = pools.reduce((sum, pool) => sum + (Number(pool.allocated) || 0), 0);
  const free = pools.reduce((sum, pool) => sum + (Number(pool.free) || 0), 0);
  const storagePercent = percentage(used, total);
  document.querySelector('#storage-ring').style.setProperty('--usage', `${storagePercent}%`);
  document.querySelector('#storage-percent').textContent = available ? `${storagePercent.toFixed(1)}%` : '—';
  document.querySelector('#storage-pool-name').textContent = pools.length ? pools.map(pool => pool.name).join(' + ') : '스토리지';
  document.querySelector('#storage-total').textContent = available ? formatBytes(total) : '—';
  document.querySelector('#storage-used').textContent = available ? formatBytes(used) : '—';
  document.querySelector('#storage-free').textContent = available ? formatBytes(free) : '—';

  const resources = available ? (activity.resources || {}) : {};
  const cpu = Number(resources.cpu_percent) || 0;
  document.querySelector('#cpu-current').textContent = available ? `${cpu.toFixed(1)}%` : '—';
  document.querySelector('#cpu-meter').style.width = `${available ? cpu : 0}%`;
  document.querySelector('#cpu-detail').textContent = available ? `${resources.cpu_model || 'CPU'} · ${resources.cpu_cores || '—'}코어` : 'NAS 오프라인';
  const memory = resources.memory || {};
  const memoryPercent = percentage(memory.used_bytes, memory.total_bytes);
  const arcPercent = percentage(memory.arc_bytes, memory.total_bytes);
  const otherMemory = Math.max(0, (Number(memory.used_bytes) || 0) - (Number(memory.arc_bytes) || 0));
  const otherPercent = percentage(otherMemory, memory.total_bytes);
  document.querySelector('#memory-current').textContent = available ? `${memoryPercent.toFixed(1)}%` : '—';
  document.querySelector('#memory-other-meter').style.width = `${available ? otherPercent : 0}%`;
  document.querySelector('#memory-arc-meter').style.width = `${available ? arcPercent : 0}%`;
  document.querySelector('#memory-detail').textContent = available ? `ARC 외 ${formatBytes(otherMemory)} · ARC ${formatBytes(memory.arc_bytes)}` : 'NAS 오프라인';
  const temperatures = resources.temperatures || {};
  document.querySelector('#temperature-current').textContent = available && temperatures.max_c != null ? `${Number(temperatures.max_c).toFixed(0)}°C` : '—';
  const temperatureList = document.querySelector('#temperature-list');
  temperatureList.replaceChildren();
  const entries = [['CPU', temperatures.cpu_c], ...Object.entries(temperatures.disks || {})];
  entries.filter(([, value]) => value != null).forEach(([name, value]) => {
    const badge = document.createElement('span'); badge.className = 'temperature-badge'; badge.textContent = `${name} ${Number(value).toFixed(0)}°`;
    temperatureList.append(badge);
  });
  if (!temperatureList.children.length) temperatureList.textContent = available ? '온도 정보 없음' : 'NAS 오프라인';
}

const svgNamespace = 'http://www.w3.org/2000/svg';
function svgElement(name, attributes = {}) {
  const element = document.createElementNS(svgNamespace, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function renderMetricChart(id, series, formatter, fixedMax = null) {
  const svg = document.querySelector(`#${id}`);
  svg.replaceChildren();
  const samples = state.metrics?.samples || [];
  if (!samples.length) {
    const empty = svgElement('text', { x: 400, y: 115, class: 'chart-empty' }); empty.textContent = '아직 기록이 없습니다'; svg.append(empty); return;
  }
  const left = 72, right = 18, top = 15, bottom = 35, width = 800 - left - right, height = 220 - top - bottom;
  const allValues = samples.flatMap(sample => series.map(item => Number(item.value(sample)) || 0));
  const maxValue = fixedMax || Math.max(1, ...allValues) * 1.12;
  [0, .5, 1].forEach(fraction => {
    const y = top + height * (1 - fraction);
    svg.append(svgElement('line', { x1: left, y1: y, x2: left + width, y2: y, class: 'chart-gridline' }));
    const label = svgElement('text', { x: left - 9, y: y + 6, class: 'chart-label', 'text-anchor': 'end' }); label.textContent = formatter(maxValue * fraction); svg.append(label);
  });
  const firstTime = Number(samples[0].sampled_at), lastTime = Number(samples.at(-1).sampled_at);
  const span = Math.max(1, lastTime - firstTime);
  const dateFormat = new Intl.DateTimeFormat('ko-KR', state.metricRange === '24h' ? { hour: '2-digit', minute: '2-digit' } : { month: 'numeric', day: 'numeric' });
  [0, .5, 1].forEach(fraction => {
    const label = svgElement('text', { x: left + width * fraction, y: 212, class: 'chart-label', 'text-anchor': fraction === 0 ? 'start' : fraction === 1 ? 'end' : 'middle' });
    label.textContent = dateFormat.format(new Date((firstTime + span * fraction) * 1000)); svg.append(label);
  });
  series.forEach(item => {
    const points = samples.map((sample, index) => {
      const x = left + width * (Number(sample.sampled_at) - firstTime) / span;
      const y = top + height * (1 - Math.min(maxValue, Number(item.value(sample)) || 0) / maxValue);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    if (samples.length === 1) {
      svg.append(svgElement('circle', { cx: left + width / 2, cy: top + height * (1 - Math.min(maxValue, Number(item.value(samples[0])) || 0) / maxValue), r: 4, fill: item.color }));
    } else {
      svg.append(svgElement('polyline', { points, class: 'chart-line', stroke: item.color }));
    }
  });
}

function formatPeakTime(timestamp) {
  return timestamp ? new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp * 1000)) : '기록 없음';
}

function renderMetrics() {
  const peaks = state.metrics?.peaks || {};
  const peakGrid = document.querySelector('#peak-grid'); peakGrid.replaceChildren();
  const peakItems = [
    ['CPU 최고', peaks.cpu, value => `${value.toFixed(1)}%`],
    ['메모리 최고', peaks.memory, value => `${value.toFixed(1)}%`],
    ['ARC 캐시 최고', peaks.arc_memory, value => `${value.toFixed(1)}%`],
    ['최고 온도', peaks.temperature, value => `${value.toFixed(0)}°C`],
    ['네트워크 피크', peaks.network, formatRate],
    ['디스크 피크', peaks.disk, formatRate],
  ];
  peakItems.forEach(([label, peak, format]) => {
    const card = document.createElement('article'); card.className = 'peak-card';
    const title = document.createElement('span'); title.textContent = label;
    const value = document.createElement('strong'); value.textContent = peak ? format(Number(peak.value) || 0) : '—';
    const time = document.createElement('small'); time.textContent = peak ? formatPeakTime(peak.sampled_at) : '기록 없음';
    card.append(title, value, time); peakGrid.append(card);
  });
  const style = getComputedStyle(document.documentElement);
  const green = style.getPropertyValue('--green').trim(), blue = style.getPropertyValue('--blue').trim(), red = style.getPropertyValue('--red').trim(), purple = style.getPropertyValue('--purple').trim();
  renderMetricChart('resource-chart', [
    { value: sample => sample.cpu_percent, color: green },
    { value: sample => percentage(sample.memory_used_bytes, sample.memory_total_bytes), color: blue },
    { value: sample => percentage(sample.memory_arc_bytes, sample.memory_total_bytes), color: purple },
  ], value => `${Math.round(value)}%`, 100);
  renderMetricChart('temperature-chart', [
    { value: sample => sample.max_temp_c, color: red },
    { value: sample => sample.cpu_temp_c, color: blue },
  ], value => `${Math.round(value)}°`);
  renderMetricChart('network-chart', [
    { value: sample => sample.network_rx_bps, color: green },
    { value: sample => sample.network_tx_bps, color: blue },
  ], formatRate);
  renderMetricChart('disk-chart', [
    { value: sample => sample.disk_read_bps, color: green },
    { value: sample => sample.disk_write_bps, color: blue },
  ], formatRate);
  const count = state.metrics?.samples?.length || 0;
  document.querySelector('#metrics-note').textContent = count ? `${count}개 구간 · ${Math.round((state.metrics.bucket_seconds || 60) / 60)}분 평균 · 최고값은 원본 1분 기록 기준` : '지금부터 1분 단위 기록을 시작합니다.';
}

function activityItem(title, meta, percent = null) {
  const item = document.createElement('div');
  item.className = 'activity-item';
  const marker = document.createElement('span');
  marker.className = 'activity-marker';
  marker.textContent = '●';
  const body = document.createElement('div');
  const heading = document.createElement('strong');
  heading.textContent = title;
  const detail = document.createElement('span');
  detail.textContent = meta;
  body.append(heading, detail);
  if (percent !== null) {
    const progress = document.createElement('div');
    progress.className = 'activity-progress';
    const bar = document.createElement('span');
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    progress.append(bar); body.append(progress);
  }
  item.append(marker, body);
  return item;
}

function renderActivity() {
  const activity = state.activity;
  const list = document.querySelector('#activity-list');
  const summary = document.querySelector('#activity-summary');
  list.replaceChildren(); summary.replaceChildren();
  if (!activity || !activity.available || !state.status?.online) {
    ['disk-read-rate', 'disk-write-rate', 'network-rx-rate', 'network-tx-rate'].forEach(id => { document.querySelector(`#${id}`).textContent = '—'; });
    document.querySelector('#activity-updated').textContent = state.status?.online ? '현재 활동 정보를 불러오지 못했습니다.' : 'NAS가 켜지면 활동 정보가 표시됩니다.';
    list.innerHTML = '<div class="activity-empty">표시할 활동 정보가 없습니다.</div>';
    renderResources();
    return;
  }
  const io = activity.io || {};
  document.querySelector('#disk-read-rate').textContent = formatRate(io.disk_read_bps);
  document.querySelector('#disk-write-rate').textContent = formatRate(io.disk_write_bps);
  document.querySelector('#network-rx-rate').textContent = formatRate(io.network_rx_bps);
  document.querySelector('#network-tx-rate').textContent = formatRate(io.network_tx_bps);
  const checked = activity.checked_at ? new Date(activity.checked_at * 1000) : null;
  document.querySelector('#activity-updated').textContent = checked ? `${checked.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} 기준` : '방금 확인함';

  const counts = activity.summary || {};
  [['Time Machine', counts.time_machine_backups || 0], ['SMB 연결', counts.smb_sessions || 0], ['열린 SMB 파일', counts.smb_open_files || 0], ['실행 작업', counts.active_jobs || 0], ['스토리지 검사', counts.active_scans || 0], ['iSCSI 연결', counts.iscsi_sessions || 0]].forEach(([label, count]) => {
    const chip = document.createElement('span');
    chip.className = count ? 'activity-chip active' : 'activity-chip';
    chip.textContent = `${label} ${count}`;
    summary.append(chip);
  });
  (activity.jobs || []).forEach(job => list.append(activityItem(job.description || job.method, `${job.state === 'WAITING' ? '대기 중' : '실행 중'} · ${job.method}`, job.percent)));
  (activity.active_scans || []).forEach(scan => list.append(activityItem(`${scan.pool} ${scan.function === 'RESILVER' ? '복구' : '스토리지 검사'}`, `${Math.round(scan.percent || 0)}% 진행`, scan.percent)));
  (activity.iscsi_sessions || []).forEach(session => list.append(activityItem(`${session.target} iSCSI 연결`, session.client)));
  const timeMachineShares = new Set();
  (activity.time_machine_backups || []).forEach(backup => {
    timeMachineShares.add(backup.share);
    const identity = [backup.usernames?.join(', '), backup.clients?.join(', ')].filter(Boolean).join(' · ');
    const meta = [`${backup.share}`, identity, `열린 파일 ${backup.open_files || 0}개`].filter(Boolean).join(' · ');
    list.append(activityItem(`${backup.name} Time Machine 백업 활성`, meta));
  });
  (activity.smb_connections || []).filter(connection => !timeMachineShares.has(connection.share)).forEach(connection => {
    const identity = [connection.username, connection.client].filter(Boolean).join(' · ');
    list.append(activityItem(`${connection.share} SMB 연결`, identity));
  });
  if (!list.children.length) list.innerHTML = '<div class="activity-empty good">TrueNAS에서 감지된 작업이나 파일 공유 활동이 없습니다.</div>';
  renderResources();
}

const dayNames = ['월', '화', '수', '목', '금', '토', '일'];
function repeatLabel(days) {
  if (days.length === 7) return '매일';
  if (JSON.stringify(days) === JSON.stringify([0,1,2,3,4])) return '평일';
  if (JSON.stringify(days) === JSON.stringify([5,6])) return '주말';
  return days.map(day => dayNames[day]).join('·');
}

function formatNext(iso) {
  if (!iso) return '비활성화됨';
  return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric', weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(iso));
}

function scheduleCard(item, editable) {
  const card = document.createElement('article');
  card.className = 'schedule-card';
  const symbol = document.createElement('span');
  symbol.className = 'schedule-symbol';
  symbol.textContent = item.action === 'wake' ? '☀' : '☾';
  const body = document.createElement('div');
  const title = document.createElement('div');
  title.className = 'schedule-title';
  title.textContent = `${item.name} · ${item.time}`;
  const meta = document.createElement('div');
  meta.className = 'schedule-meta';
  meta.textContent = `${repeatLabel(item.weekdays)} · 다음 실행 ${formatNext(item.next_run)}`;
  body.append(title, meta);
  const chip = document.createElement('span');
  chip.className = 'chip';
  chip.textContent = item.action === 'wake' ? 'WOL + 상태 점검' : '정상 종료';
  const buttons = document.createElement('div');
  buttons.className = 'schedule-buttons';
  if (editable) {
    const toggle = document.createElement('button');
    toggle.className = 'small-button';
    toggle.type = 'button';
    toggle.textContent = item.enabled ? '켜짐' : '꺼짐';
    toggle.setAttribute('aria-label', `${item.name} ${item.enabled ? '비활성화' : '활성화'}`);
    toggle.addEventListener('click', () => saveSchedule({ ...item, enabled: !item.enabled }));
    const edit = document.createElement('button');
    edit.className = 'small-button';
    edit.type = 'button';
    edit.textContent = '편집';
    edit.addEventListener('click', () => openSchedule(item));
    const remove = document.createElement('button');
    remove.className = 'small-button';
    remove.type = 'button';
    remove.textContent = '삭제';
    remove.addEventListener('click', () => deleteSchedule(item));
    buttons.append(toggle, edit, remove);
  }
  card.append(symbol, body, chip, buttons);
  return card;
}

function renderSchedules() {
  const upcoming = document.querySelector('#upcoming-schedules');
  const all = document.querySelector('#all-schedules');
  upcoming.replaceChildren(); all.replaceChildren();
  const enabled = state.schedules.filter(item => item.enabled).sort((a, b) => new Date(a.next_run) - new Date(b.next_run)).slice(0, 3);
  if (!enabled.length) upcoming.innerHTML = '<div class="empty-state">활성화된 예약이 없습니다.</div>';
  else enabled.forEach(item => upcoming.append(scheduleCard(item, false)));
  if (!state.schedules.length) all.innerHTML = '<div class="empty-state">아직 예약이 없습니다. 첫 예약을 만들어보세요.</div>';
  else state.schedules.forEach(item => all.append(scheduleCard(item, true)));
}

function renderHistory() {
  const body = document.querySelector('#history-body');
  body.replaceChildren();
  if (!state.history.length) {
    const row = body.insertRow();
    const cell = row.insertCell(); cell.colSpan = 5; cell.textContent = '아직 실행 기록이 없습니다.';
    return;
  }
  for (const item of state.history) {
    const row = body.insertRow();
    const started = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(item.started_at));
    const source = item.source === 'manual' ? '수동' : item.source.startsWith('schedule:') ? '예약' : item.source;
    const resultNames = { success: '성공', failed: '실패', running: '진행 중', skipped: '건너뜀' };
    const values = [started, item.action === 'wake' ? '켜기' : '끄기', source, resultNames[item.status] || item.status, item.duration_seconds == null ? '—' : `${Math.round(item.duration_seconds)}초`];
    values.forEach((value, index) => { const cell = row.insertCell(); cell.textContent = value; if (index === 3) cell.className = `result-${item.status}`; });
    if (item.detail) row.title = item.detail;
  }
}

function renderSettings() {
  const settings = state.settings;
  const list = document.querySelector('#nas-settings');
  list.replaceChildren();
  [['NAS 주소', settings.nas_ip], ['MAC 주소', settings.mac_address], ['TrueNAS API', settings.truenas_ws_url], ['API 사용자', settings.truenas_username || '미설정'], ['API 키', settings.api_key_configured ? 'Keychain에 저장됨' : '미설정']].forEach(([term, value]) => {
    const row = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd');
    dt.textContent = term; dd.textContent = value; row.append(dt, dd); list.append(row);
  });
  document.querySelector('#setup-card').hidden = settings.api_key_configured;
}

function openSchedule(item = null) {
  const form = document.querySelector('#schedule-form');
  form.reset();
  document.querySelector('#schedule-id').value = item?.id || '';
  document.querySelector('#schedule-dialog-title').textContent = item ? '예약 편집' : '새 예약';
  document.querySelector('#schedule-name').value = item?.name || '';
  document.querySelector('#schedule-action').value = item?.action || 'wake';
  document.querySelector('#schedule-time').value = item?.time || '07:00';
  document.querySelector('#schedule-enabled').checked = item?.enabled ?? true;
  form.querySelectorAll('.weekday-picker input').forEach(input => { input.checked = item ? item.weekdays.includes(Number(input.value)) : true; });
  document.querySelector('#schedule-dialog').showModal();
}

async function saveSchedule(item) {
  try {
    const path = item.id ? `/api/schedules/${item.id}` : '/api/schedules';
    await api(path, { method: 'POST', body: JSON.stringify(item) });
    state.schedules = await api('/api/schedules');
    renderSchedules();
    document.querySelector('#schedule-dialog').close();
    showNotice('예약을 저장했습니다.');
  } catch (error) { showNotice(error.message, true); }
}

async function deleteSchedule(item) {
  if (!window.confirm(`“${item.name}” 예약을 삭제할까요?`)) return;
  try {
    await api(`/api/schedules/${item.id}`, { method: 'DELETE' });
    state.schedules = await api('/api/schedules'); renderSchedules(); showNotice('예약을 삭제했습니다.');
  } catch (error) { showNotice(error.message, true); }
}

async function triggerAction(action) {
  try {
    await api(`/api/actions/${action}`, { method: 'POST', body: JSON.stringify(action === 'shutdown' ? { confirm: 'shutdown' } : {}) });
    if (action === 'shutdown') document.querySelector('#shutdown-dialog').close();
    showNotice(action === 'wake' ? 'NAS 켜기를 시작했습니다.' : '정상 종료를 요청했습니다.');
    await refreshStatus();
  } catch (error) { showNotice(error.message, true); }
}

async function refreshStatus(force = false) {
  try {
    state.status = await api(force ? '/api/status/refresh' : '/api/status', force ? { method: 'POST', body: '{}' } : {});
    renderStatus();
    renderActivity();
    if (state.status.action) window.setTimeout(refreshStatus, 3000);
  } catch (error) { showNotice(error.message, true); }
}

async function refreshActivity(force = false) {
  const button = document.querySelector('#activity-refresh-button');
  if (force) button.disabled = true;
  try {
    state.activity = await api(force ? '/api/activity/refresh' : '/api/activity', force ? { method: 'POST', body: '{}' } : {});
    renderActivity();
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = false; }
}

async function refreshMetrics(range = state.metricRange) {
  try {
    state.metricRange = range;
    state.metrics = await api(`/api/metrics?range=${encodeURIComponent(range)}`);
    document.querySelectorAll('[data-metric-range]').forEach(button => button.classList.toggle('is-active', button.dataset.metricRange === range));
    renderMetrics();
  } catch (error) { showNotice(error.message, true); }
}

async function initialize() {
  try {
    const data = await api('/api/bootstrap');
    Object.assign(state, data);
    renderStatus(); renderActivity(); renderMetrics(); renderSchedules(); renderHistory(); renderSettings();
  } catch (error) { showNotice(`서비스 데이터를 불러오지 못했습니다: ${error.message}`, true); }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => showPage(button.dataset.page)));
  document.querySelectorAll('[data-page-link]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.pageLink)));
  document.querySelectorAll('[data-metric-range]').forEach(button => button.addEventListener('click', () => refreshMetrics(button.dataset.metricRange)));
  document.querySelectorAll('[data-new-schedule]').forEach(button => button.addEventListener('click', () => openSchedule()));
  document.querySelector('#refresh-button').addEventListener('click', async () => { await refreshStatus(true); await refreshActivity(true); await refreshMetrics(); });
  document.querySelector('#activity-refresh-button').addEventListener('click', () => refreshActivity(true));
  document.querySelector('#wake-button').addEventListener('click', () => triggerAction('wake'));
  document.querySelector('#shutdown-button').addEventListener('click', () => {
    if (!state.status.api_key_configured) {
      showPage('settings');
      showNotice('TrueNAS HTTPS와 API 키를 설정하면 안전하게 끄기를 사용할 수 있습니다.', true);
      return;
    }
    document.querySelector('#shutdown-dialog').showModal();
  });
  document.querySelector('#shutdown-form').addEventListener('submit', event => { event.preventDefault(); triggerAction('shutdown'); });
  document.querySelector('#schedule-form').addEventListener('submit', event => {
    event.preventDefault();
    const weekdays = [...event.currentTarget.querySelectorAll('.weekday-picker input:checked')].map(input => Number(input.value));
    saveSchedule({ id: Number(document.querySelector('#schedule-id').value) || undefined, name: document.querySelector('#schedule-name').value, action: document.querySelector('#schedule-action').value, time: document.querySelector('#schedule-time').value, weekdays, enabled: document.querySelector('#schedule-enabled').checked });
  });
  initialize();
  window.setInterval(() => refreshStatus(false), 15000);
  window.setInterval(() => refreshActivity(false), 15000);
  window.setInterval(() => refreshMetrics(), 60000);
});
