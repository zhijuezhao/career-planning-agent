import type { GuideStep } from '@/api/journey'

export interface GuideStepMeta {
  key: GuideStep
  label: string      // 短标题（stepper 节点）
  title: string      // 页内大标题
  route: string      // /guide/resume 等
  stepperIndex: number  // 0..4
}

export const GUIDE_STEPS: GuideStepMeta[] = [
  { key: 'resume', label: '简历', title: '上传简历', route: '/guide/resume', stepperIndex: 0 },
  { key: 'parse', label: '解析', title: '画像解析', route: '/guide/parse', stepperIndex: 1 },
  { key: 'match', label: '选岗', title: '选择岗位', route: '/guide/match', stepperIndex: 2 },
  { key: 'career', label: '策略', title: '匹配策略', route: '/guide/career', stepperIndex: 3 },
  { key: 'done', label: '报告', title: '生成报告', route: '/guide/done', stepperIndex: 4 },
]

export const GUIDE_STEP_MAP = Object.fromEntries(GUIDE_STEPS.map(s => [s.key, s])) as Record<GuideStep, GuideStepMeta>

export const ZONE_META: Record<string, { label: string; route: string }> = {
  welcome: { label: '欢迎', route: '/welcome' },
  guide: { label: '引导', route: '/guide/resume' },
  business: { label: '业务区', route: '/' },
}