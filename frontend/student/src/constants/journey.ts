import type { JourneyStage } from '@/api/journey'

export const STAGE_META: Record<JourneyStage, { label: string; title: string; route: string; stepperIndex: number }> = {
  start:    { label: '开始',     title: '开始',     route: '/start',     stepperIndex: 0 },
  upload:   { label: '上传简历', title: '上传简历', route: '/upload',    stepperIndex: 1 },
  parsing:  { label: '画像解析', title: '画像解析', route: '/parsing',   stepperIndex: 2 },
  jobs:     { label: '选择岗位', title: '选择岗位', route: '/jobs',      stepperIndex: 3 },
  matching: { label: '人岗匹配', title: '人岗匹配', route: '/matching',  stepperIndex: 4 },
  career:   { label: '成长路线', title: '成长路线', route: '/career',    stepperIndex: 5 },
  report:   { label: '职业报告', title: '职业报告', route: '/report',    stepperIndex: 6 },
  done:     { label: '成果总览', title: '成果总览', route: '/dashboard', stepperIndex: 7 },
}