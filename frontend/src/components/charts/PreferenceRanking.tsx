import { useState } from 'react';
import './PreferenceRanking.css';
import type { Insights } from '../../lib/types';

type Attribute = Insights['attributes'][number];
interface TasteProps { insights: Insights }
const signed = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)}`;
const direction = (value: number) => value > 0 ? '좋아하는 쪽' : value < 0 ? '덜 좋아하는 쪽' : '중립';
const domain = (attributes: Attribute[]) => Math.max(1, ...attributes.map(item => Math.abs(item.weight)));
const tone = (value: number) => value > 0 ? 'taste-positive' : value < 0 ? 'taste-negative' : 'taste-neutral';

function ChartIntro({ insights }: TasteProps) {
  return <p className="taste-intro">피드백 {insights.stats.feedback_count}회 반영 · 현재 선호 가중치</p>;
}
function Selection({ attribute }: { attribute: Attribute | undefined }) {
  if (!attribute) return null;
  return <div className="taste-selection" aria-live="polite"><p key={attribute.key}><strong>{attribute.label}</strong><span>학습 전 0 → 현재 <b className={tone(attribute.weight)}>{signed(attribute.weight)}</b></span></p></div>;
}
function Footnote() {
  return <p className="taste-footnote">0은 중립이에요. 값은 선호 가중치이며, +는 좋아하는 쪽, −는 덜 좋아하는 쪽이에요.</p>;
}


const filters = [{ key: 'all', label: '전체' }, { key: 'positive', label: '좋아함' }, { key: 'negative', label: '덜 좋아함' }] as const;
export default function PreferenceRanking({ insights }: TasteProps) {
  const [filter, setFilter] = useState<'all' | 'positive' | 'negative'>('all');
  const [selected, setSelected] = useState(insights.attributes[0]?.key);
  const max = domain(insights.attributes);
  const items = [...insights.attributes].filter(item => filter === 'all' || (filter === 'positive' ? item.weight > 0 : item.weight < 0)).sort((a,b) => filter === 'negative' ? a.weight - b.weight : b.weight - a.weight);
  return <div className="taste-ranking"><ChartIntro insights={insights} />
    <div className="taste-filters" role="group" aria-label="선호 방향 필터">{filters.map(item => <button type="button" key={item.key} aria-pressed={filter === item.key} onClick={() => setFilter(item.key)}>{item.label}</button>)}</div>
    <ul className="taste-ranked-list" aria-label="선호 가중치순 특성 목록">{items.map(item => <li key={item.key}><button type="button" aria-pressed={selected === item.key} onClick={() => setSelected(item.key)}>
      <span className="taste-ranked-title"><strong>{item.label}</strong><span className={tone(item.weight)}>{signed(item.weight)}</span></span>
      <span className="taste-ranked-caption">{direction(item.weight)}<span className="taste-mini-track" aria-hidden><span className={`taste-mini-bar ${tone(item.weight)}`} style={{ width: `${Math.abs(item.weight)/max*100}%` }} /></span></span>
    </button></li>)}</ul>
    {items.length === 0 && <p className="taste-empty">이 방향으로 학습된 특성이 아직 없어요.</p>}
    <p className="taste-scale">막대는 가중치의 크기예요. 기준 {max.toFixed(1)} · 같은 값은 같은 선호예요.</p>
    <Selection attribute={items.find(item => item.key === selected)} /><Footnote />
  </div>;
}
