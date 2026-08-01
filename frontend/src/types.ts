export type User = { id: number; email: string; name: string; timezone: string; occupation?: string; avatar_color: string; email_verified:boolean; created_at: string }
export type Tokens = { access_token: string; refresh_token?: string; expires_in: number; user: User }
export type EventItem = { id: number; title: string; description?: string; start_at: string; end_at: string; category: string; color: string; location?: string; recurrence_rule?: string; reminder_minutes?: number }
export type Task = { id: number; title: string; notes?: string; due_at?: string; priority: 'low'|'medium'|'high'|'urgent'; status: 'todo'|'in_progress'|'done'|'cancelled'; estimate_minutes: number; energy: string; project?: string; reminder_at?: string; completed_at?: string }
export type GoalStep = { id: number; title: string; order_index: number; due_date?: string; is_completed: boolean }
export type Goal = { id: number; title: string; description?: string; horizon: string; target_date?: string; progress: number; status: string; steps: GoalStep[] }
export type Habit = { id: number; title: string; emoji: string; cadence: string; target_per_week: number; color: string; archived: boolean; current_streak: number; best_streak: number; completed_today: boolean; week_count: number }
export type Overload = { level: string; score: number; scheduled_minutes: number; open_tasks: number; urgent_tasks: number; signals: string[]; suggestion: string }
export type Dashboard = { greeting: string; date_label: string; focus_score: number; tasks_due: number; completed_today: number; habit_rate: number; events_today: EventItem[]; priority_tasks: Task[]; goals: Goal[]; habits: Habit[]; overload: Overload; recommendation?: {id:number; title:string; body:string; kind:string; action?:string} }
export type Analytics = { period_days:number; tasks_completed:number; task_completion_rate:number; focus_minutes:number; habit_completion_rate:number; active_goal_progress:number; balance_score?:number; productive_days:{date:string;completed:number}[]; category_minutes:Record<string,number> }
export type Balance = { id:number; assessment_date:string; health:number; career:number; finance:number; relationships:number; growth:number; recreation:number; environment:number; contribution:number; note?:string; average:number }
export type Recommendation = { id:number; kind:string; title:string; body:string; action?:string; status:string; created_at:string }
export type AIActionProposal = { id:number; type:string; title:string; description:string; status:string; requires_confirmation:boolean }
export type ChatMessage = { id?:number; conversation_id?:number; role:'user'|'assistant'|'system'; content:string; created_at?:string; proposals?:AIActionProposal[] }
export type AIConversation = { id:number; title:string; created_at:string; updated_at:string }
export type AIStatus = { available:boolean; provider:string; model:string; message:string }
export type GoalMilestone = { title:string; description:string; deadline:string; success_criteria:string[] }
export type GoalPlanTask = { title:string; description:string; priority:string; estimated_minutes:number; deadline?:string }
export type GoalPlanHabit = { title:string; frequency:string; duration_minutes:number }
export type GoalScheduleSuggestion = { title:string; preferred_days:string[]; preferred_time:string; duration_minutes:number }
export type GoalPlanPayload = {
  goal_summary:string; strategy:string; assumptions:string[]; clarifying_questions:string[]
  milestones:GoalMilestone[]; monthly_actions:{month:string;actions:string[]}[]
  weekly_plan:{day_of_week:string;duration_minutes:number;action:string}[]; tasks:GoalPlanTask[]
  habits:GoalPlanHabit[]; schedule_suggestions:GoalScheduleSuggestion[]
  risks:{risk:string;mitigation:string}[]; progress_metrics:{name:string;target:string}[]
  first_next_action:{title:string;estimated_minutes:number}
}
export type GoalPlan = { id:number; goal_id:number; status:string; version:number; plan:GoalPlanPayload; diff?:{added:string[];removed:string[];moved:string[];reason:string}; created_at:string; updated_at:string }
export type Settings = { theme:string; language:string; notifications_enabled:boolean; daily_digest_time:string; workday_start:string; workday_end:string; weekly_focus_hours:number; compact_mode:boolean; ai_tone:string; ai_context_consent_version?:string; ai_context_consent_at?:string; ai_context_consent_revoked_at?:string }
export type AIConsent = { required:boolean; active:boolean; policy_version:string; accepted_at?:string; revoked_at?:string }
export type CalendarView = 'day'|'week'|'month'
export type EnergyPoint = { hour:number; level:number; kind:'peak'|'steady'|'dip'|'recovery'; activity:string; recommendation:string }
export type EnergyFactor = { label:string; value:string; impact:string; tone:'positive'|'negative'|'neutral' }
export type EnergyRecommendation = { time:string; title:string; body:string; kind:string }
export type EnergyForecast = { date:string; score:number; status:string; peak_start:string; peak_end:string; points:EnergyPoint[]; factors:EnergyFactor[]; recommendations:EnergyRecommendation[] }
