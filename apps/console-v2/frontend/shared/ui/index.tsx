import { useId, useRef } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, KeyboardEvent as ReactKeyboardEvent, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import './styles.css';

type Tone = 'interaction' | 'telemetry' | 'success' | 'warn' | 'danger' | 'muted' | 'blue' | 'green' | 'amber' | 'red';
const cx = (...names: Array<string | false | null | undefined>) => names.filter(Boolean).join(' ');

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'quiet'; size?: 'sm' | 'md' | 'lg'; loading?: boolean }
export function Button({ className, variant = 'secondary', size = 'md', loading = false, disabled, type = 'button', children, ...props }: ButtonProps) { return <button {...props} type={type} className={cx('ui-button', `ui-button-${variant}`, `ui-button-${size}`, className)} disabled={disabled || loading} aria-busy={loading || undefined}>{loading ? <LoadingIndicator label="" size="sm" /> : children}</button>; }
export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { label: string; size?: 'sm' | 'md' | 'lg' }
export function IconButton({ label, className, size = 'md', children, ...props }: IconButtonProps) { return <button {...props} type={props.type ?? 'button'} className={cx('ui-icon-button', `ui-icon-button-${size}`, className)} aria-label={label}>{children}</button>; }

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> { label?: string; error?: string; hint?: string }
export function Select({ label, id, className, error, hint, children, ...props }: SelectProps) { const generatedId = useId(); const inputId = id ?? (label ? `select-${generatedId.replace(/:/g, '')}` : undefined); return <div className="ui-field">{label && <label className="ui-field-label" htmlFor={inputId}>{label}</label>}<span className={cx('ui-select-control', props.disabled && 'is-disabled')}><select {...props} id={inputId} className={cx('ui-select', className)} aria-invalid={error ? true : props['aria-invalid']}>{children}</select></span>{hint && !error && <small className="ui-field-hint">{hint}</small>}{error && <small className="ui-field-error">{error}</small>}</div>; }
export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; error?: string; hint?: string }
export function TextField({ label, id, className, error, hint, ...props }: TextFieldProps) { const generatedId = useId(); const inputId = id ?? (label ? `field-${generatedId.replace(/:/g, '')}` : undefined); return <label className="ui-field">{label && <span className="ui-field-label">{label}</span>}<input {...props} id={inputId} className={cx('ui-input', props.type === 'number' && 'ui-number-input', className)} aria-invalid={error ? true : props['aria-invalid']} />{hint && !error && <small className="ui-field-hint">{hint}</small>}{error && <small className="ui-field-error">{error}</small>}</label>; }
export function TextArea({ label, id, className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) { const generatedId = useId(); const inputId = id ?? (label ? `textarea-${generatedId.replace(/:/g, '')}` : undefined); return <label className="ui-field">{label && <span className="ui-field-label">{label}</span>}<textarea {...props} id={inputId} className={cx('ui-textarea', className)} /></label>; }
export interface NumberValueProps { value: ReactNode; unit?: ReactNode; editable?: boolean; className?: string; ariaLabel?: string }
export function NumberValue({ value, unit, editable = false, className, ariaLabel }: NumberValueProps) { return <span className={cx('ui-number-value', editable && 'ui-number-value-editable', className)} aria-label={ariaLabel}>{value}{unit && <small>{unit}</small>}</span>; }
export function Slider({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) { return <input {...props} type="range" className={cx('ui-slider', className)} />; }
export function Checkbox({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) { return <label className={cx('ui-check', className)}><input {...props} type="checkbox" /><span className="ui-check-box" aria-hidden="true" />{label && <span>{label}</span>}</label>; }
export function Radio({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) { return <label className={cx('ui-radio', className)}><input {...props} type="radio" /><span className="ui-radio-dot" aria-hidden="true" />{label && <span>{label}</span>}</label>; }
export interface SegmentOption { value: string; label: ReactNode; disabled?: boolean }
export function SegmentedControl({ options, value, onChange, name, className, disabled, ariaLabel }: { options: SegmentOption[]; value: string; onChange: (value: string) => void; name?: string; className?: string; disabled?: boolean; ariaLabel?: string }) {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabledOptions = options.filter(option => !disabled && !option.disabled);
  const focusOption = (option: SegmentOption | undefined) => {
    if (!option) return;
    const index = options.findIndex(candidate => candidate.value === option.value);
    buttonRefs.current[index]?.focus();
    onChange(option.value);
  };
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    if (enabledOptions.length === 0) return;
    event.preventDefault();
    const current = enabledOptions.findIndex(option => options[index]?.value === option.value);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? enabledOptions.length - 1 : (current + (event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1) + enabledOptions.length) % enabledOptions.length;
    focusOption(enabledOptions[nextIndex]);
  };
  return <div className={cx('ui-segmented', className)} role="radiogroup" aria-label={ariaLabel}>{options.map((option, index) => <button key={option.value} ref={element => { buttonRefs.current[index] = element; }} type="button" role="radio" aria-checked={value === option.value} tabIndex={value === option.value ? 0 : -1} className={value === option.value ? 'is-selected' : undefined} disabled={disabled || option.disabled} name={name} onKeyDown={event => handleKeyDown(event, index)} onClick={() => onChange(option.value)}>{option.label}</button>)}</div>;
}
export interface Tab { value: string; label: ReactNode; panel?: ReactNode; disabled?: boolean }
export function Tabs({ tabs, value, onChange, className, id = 'tabs' }: { tabs: Tab[]; value: string; onChange: (value: string) => void; className?: string; id?: string }) { return <div className={cx('ui-tabs', className)}><div className="ui-tabs-list" role="tablist">{tabs.map(tab => <button key={tab.value} type="button" role="tab" id={`${id}-${tab.value}`} aria-selected={tab.value === value} aria-controls={`${id}-panel-${tab.value}`} tabIndex={tab.value === value ? 0 : -1} disabled={tab.disabled} onClick={() => onChange(tab.value)}>{tab.label}</button>)}</div>{tabs.map(tab => tab.value === value && <div key={tab.value} id={`${id}-panel-${tab.value}`} role="tabpanel" aria-labelledby={`${id}-${tab.value}`}>{tab.panel}</div>)}</div>; }

export function Card({ children, className = '', ...props }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLElement>) { return <section {...props} className={cx('card', className)}>{children}</section>; }
export function Badge({ children, tone = 'interaction', className }: { children: ReactNode; tone?: Tone; className?: string }) { return <span className={cx('badge', `badge-${tone}`, className)}>{children}</span>; }
export function Banner({ children, tone = 'muted', title, className }: { children: ReactNode; tone?: Tone; title?: ReactNode; className?: string }) { return <div className={cx('ui-banner', `ui-banner-${tone}`, className)} role={tone === 'danger' ? 'alert' : 'status'}>{title && <strong>{title}</strong>}<span>{children}</span></div>; }
export function Progress({ value, label }: { value: number; label?: string }) { const bounded = Math.max(0, Math.min(100, value)); return <div className="progress" role={label ? 'progressbar' : undefined} aria-label={label} aria-valuenow={label ? bounded : undefined} aria-valuemin={label ? 0 : undefined} aria-valuemax={label ? 100 : undefined}><span style={{ width: `${bounded}%` }} /></div>; }
export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) { return <div className="empty"><div className="empty-icon" aria-hidden="true">✦</div><strong>{title}</strong><span>{detail}</span>{action}</div>; }
export function LoadingIndicator({ label = 'Loading', size = 'md' }: { label?: string; size?: 'sm' | 'md' | 'lg' }) { return <span className={cx('ui-loading', `ui-loading-${size}`)} role="status" aria-label={label || undefined}><span aria-hidden="true" /></span>; }
