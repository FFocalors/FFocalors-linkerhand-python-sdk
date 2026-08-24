import { fireEvent, render, screen } from '@testing-library/react';
import { Button, Checkbox, NumberValue, SegmentedControl, Select, Tabs, TextField } from './index';

describe('shared UI primitives', () => {
  it('keeps actions and fields keyboard/label accessible', () => {
    render(<><Button>Save</Button><Button type="submit">Submit</Button><TextField label="Timeout" type="number" value={5000} readOnly /><Checkbox label="Reconnect" /></>);
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'button');
    expect(screen.getByRole('button', { name: 'Submit' })).toHaveAttribute('type', 'submit');
    expect(screen.getByLabelText('Timeout')).toHaveAttribute('type', 'number');
    expect(screen.getByRole('checkbox', { name: 'Reconnect' })).toBeInTheDocument();
  });

  it('anchors the select arrow to the control even when hint or error copy is present', () => {
    const { rerender } = render(<Select label="Mode" hint="Choose a mode"><option value="one">One</option></Select>);
    expect(screen.getByLabelText('Mode').parentElement).toHaveClass('ui-select-control');
    rerender(<Select label="Mode" error="Required"><option value="one">One</option></Select>);
    expect(screen.getByLabelText('Mode').parentElement).toHaveClass('ui-select-control');
  });

  it('exposes numeric display and segmented radio semantics', () => {
    const onChange = vi.fn();
    render(<><NumberValue value={42} unit="ms" editable /><SegmentedControl value="can" options={[{ value: 'can', label: 'CAN' }, { value: 'rs485', label: 'RS485' }]} onChange={onChange} /></>);
    expect(screen.getByText('42')).toHaveClass('ui-number-value-editable');
    fireEvent.click(screen.getByRole('radio', { name: 'RS485' }));
    expect(onChange).toHaveBeenCalledWith('rs485');
  });

  it('uses radio semantics with a roving tab stop and arrow-key navigation', () => {
    const onChange = vi.fn();
    render(<SegmentedControl value="can" options={[{ value: 'can', label: 'CAN' }, { value: 'rs485', label: 'RS485' }, { value: 'usb', label: 'USB', disabled: true }]} onChange={onChange} ariaLabel="Transport" />);
    const can = screen.getByRole('radio', { name: 'CAN' });
    const rs485 = screen.getByRole('radio', { name: 'RS485' });
    expect(screen.getByRole('radiogroup', { name: 'Transport' })).toBeInTheDocument();
    expect(can).toHaveAttribute('tabindex', '0');
    expect(rs485).toHaveAttribute('tabindex', '-1');
    can.focus();
    fireEvent.keyDown(can, { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith('rs485');
    expect(document.activeElement).toBe(rs485);
    expect(screen.getByRole('radio', { name: 'USB' })).toBeDisabled();
  });

  it('links tabs to the active panel', () => {
    render(<Tabs value="one" tabs={[{ value: 'one', label: 'One', panel: 'First' }, { value: 'two', label: 'Two', panel: 'Second' }]} onChange={vi.fn()} />);
    expect(screen.getByRole('tab', { name: 'One' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('First');
  });
});
