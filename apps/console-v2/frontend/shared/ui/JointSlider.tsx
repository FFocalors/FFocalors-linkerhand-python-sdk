import { memo, useEffect, useRef, type ChangeEvent } from 'react';
import { NumberValue } from './index';

interface JointSliderProps {
  index: number;
  value: number;
  disabled: boolean;
  label?: string;
  onBegin: (index: number) => void;
  onInput: (index: number, value: number) => void;
  onFinish: (index: number, force?: boolean) => void;
}

const clamp = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
const formatJointPercent = (value: number) => `${(Math.round(value * 1000) / 10).toFixed(1)}%`;

/** Shared low-render slider used by device control and action pose editing. */
export const JointSlider = memo(function JointSlider({ index, value, disabled, label, onBegin, onInput, onFinish }: JointSliderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const outputRef = useRef<HTMLSpanElement>(null);
  const draggingRef = useRef(false);
  useEffect(() => {
    if (draggingRef.current) return;
    if (inputRef.current) inputRef.current.value = String(value);
    if (outputRef.current) outputRef.current.textContent = formatJointPercent(value);
  }, [value]);
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = clamp(Number(event.currentTarget.value));
    if (inputRef.current) inputRef.current.value = String(next);
    if (outputRef.current) outputRef.current.textContent = formatJointPercent(next);
    onInput(index, next);
  };
  return <label className="joint-row"><span className="joint-name">{label ?? `J${index + 1}`}</span><input ref={inputRef} className="ui-slider" aria-label={`${label ?? `J${index + 1}`} 目标`} type="range" min="0" max="1" step="0.001" defaultValue={value} disabled={disabled} onPointerDown={() => { draggingRef.current = true; onBegin(index); }} onPointerUp={() => { draggingRef.current = false; onFinish(index); }} onPointerCancel={() => { draggingRef.current = false; onFinish(index); }} onBlur={() => { if (draggingRef.current) { draggingRef.current = false; onFinish(index); } }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); draggingRef.current = false; onFinish(index, true); } }} onChange={handleChange} /><NumberValue value={<span ref={outputRef}>{formatJointPercent(value)}</span>} ariaLabel={`${label ?? `J${index + 1}`} 目标值`} /></label>;
});
