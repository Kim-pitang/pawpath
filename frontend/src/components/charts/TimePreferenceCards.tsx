import { useState } from 'react';
import './TimePreferenceCards.css';
import { CloudSun, Moon, Sun, Sunrise } from 'lucide-react';
import type { Insights } from '../../lib/types';

type TimePreference = Insights['time_preferences'][number];
interface TimeProps { items: TimePreference[] }
const icons = { morning: Sunrise, lunch: Sun, afternoon: CloudSun, evening: Moon };
const recordLabel = (item: TimePreference) => item.samples > 0 ? `기록 ${item.samples}회` : '기록 없음';

function Intro({ items }: TimeProps) {
  return <p className="tp-intro">50점은 중립 · 기록 있는 시간대 {items.filter(item => item.samples > 0).length}/{items.length}</p>;
}
function Detail({ item }: { item: TimePreference | undefined }) {
  if (!item) return null;
  const difference = item.score - 50;
  return <div className="tp-detail" aria-live="polite"><div key={item.key}>
    <p><strong>{item.label}</strong><span><b>{item.score.toFixed(0)}</b>점 · 기록 {item.samples}회</span></p>
    <p>{item.samples === 0 ? '이 시간대의 기록이 아직 없어요.' : difference === 0 ? '현재 점수는 중립값 50점과 같아요.' : `현재 점수는 중립값보다 ${Math.abs(difference).toFixed(0)}점 ${difference > 0 ? '높아요' : '낮아요'}.`}</p>
  </div></div>;
}
function Note() {
  return <p className="tp-note">점수와 기록 수를 함께 봐 주세요. 기록 없는 시간대의 점수는 옅게 표시했어요.</p>;
}
function TimeIcon({ item, size = 20 }: { item: TimePreference; size?: number }) {
  const Icon = icons[item.key as keyof typeof icons] ?? Sun;
  return <Icon size={size} strokeWidth={1.6} aria-hidden />;
}


export default function TimePreferenceCards({ items }: TimeProps) {
  const [selected,setSelected]=useState(items.find(item=>item.samples>0)?.key??items[0]?.key);
  return <div className="tp-cards"><Intro items={items} />
    <div className="tp-card-grid" role="group" aria-label="시간대 선택">{items.map(item=><button type="button" key={item.key} className={item.samples===0?'tp-unrecorded':''} aria-pressed={selected===item.key} onClick={()=>setSelected(item.key)}>
      <span className="tp-card-label">{item.label}</span><TimeIcon item={item} size={28} /><span className="tp-card-score"><b>{item.score.toFixed(0)}</b>점</span><span className="tp-card-records">{recordLabel(item)}</span>
    </button>)}</div>
    <Detail item={items.find(item=>item.key===selected)} /><Note />
  </div>;
}
