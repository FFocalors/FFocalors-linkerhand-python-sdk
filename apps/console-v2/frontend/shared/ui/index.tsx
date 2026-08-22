import type { ReactNode } from 'react';
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) { return <section className={`card ${className}`}>{children}</section>; }
export function Badge({ children, tone = 'blue' }: { children: ReactNode; tone?: 'blue' | 'green' | 'amber' | 'red' }) { return <span className={`badge badge-${tone}`}>{children}</span>; }
export function Progress({ value }: { value: number }) { return <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>; }
export function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="empty"><div className="empty-icon">✦</div><strong>{title}</strong><span>{detail}</span></div>; }
