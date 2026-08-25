/** Shared O6 pose data used by device control and action composition. */
export interface DeviceControlQuickAction {
  id: string;
  label: string;
  detail?: string;
  positions?: number[];
  category?: 'basic' | 'number' | 'custom';
}

/** O6 joint display names; order matches the device capability vector. */
export const O6_JOINT_NAMES = ['大拇指弯曲', '大拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小拇指弯曲'];

export const O6_BASIC_ACTIONS: DeviceControlQuickAction[] = [
  { id: 'open', label: '张开', category: 'basic', positions: Array(6).fill(250 / 255) },
  { id: 'fist', label: '握拳', category: 'basic', positions: [102 / 255, 18 / 255, 0, 0, 0, 0] },
  { id: 'ok', label: 'OK', category: 'basic', positions: [96 / 255, 100 / 255, 118 / 255, 250 / 255, 250 / 255, 250 / 255] },
  { id: 'thumbs-up', label: '点赞', category: 'basic', positions: [250 / 255, 79 / 255, 0, 0, 0, 0] },
];

export const O6_NUMBER_ACTIONS: DeviceControlQuickAction[] = [
  { id: 'one', label: '壹', category: 'number', positions: [125 / 255, 18 / 255, 1, 0, 0, 0] },
  { id: 'two', label: '贰', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 0, 0] },
  { id: 'three', label: '叁', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 1, 0] },
  { id: 'four', label: '肆', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 1, 1] },
  { id: 'five', label: '伍', category: 'number', positions: Array(6).fill(1) },
];
