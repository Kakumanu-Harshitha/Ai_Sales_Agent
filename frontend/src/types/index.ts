export interface Lead { id: number; contact_id?: number; status?: string; source?: string; deal_value?: number; lead_score?: number; priority?: string; stage_entered_at?: string; last_activity_at?: string; created_at?: string; company_name?: string; contact_name?: string; }
export interface Campaign { id: number; name?: string; status?: string; created_at?: string; emails_sent?: number; replies?: number; }
export interface Meeting { id: number; lead_id?: number; title?: string; scheduled_at?: string; status?: string; meet_link?: string; calendar_event_id?: string; }
export interface Activity { id: number; type: string; description?: string; created_at?: string; }
export interface Signal { id: number; lead_id: number; signal_type?: string; headline?: string; description?: string; business_impact?: string; why_it_matters?: string; source_name?: string; source_url?: string; source_type?: string; published_date?: string; confidence_score?: number; score_contribution?: number; priority?: string; recommended_action?: string; suggested_pitch?: string; target_persona?: string; icp_match?: number; created_at?: string; }
export interface Call { id: number; lead_id: number; call_date?: string; duration_minutes?: number; outcome?: string; notes?: string; follow_up_required?: boolean; follow_up_date?: string; }
export interface Note { id: number; lead_id: number; content: string; created_at?: string; }
export interface SignatureTemplate { id: number; name: string; full_name?: string; designation?: string; department?: string; company?: string; email?: string; phone?: string; website?: string; linkedin?: string; address?: string; logo_url?: string; digital_signature_url?: string; header_banner_url?: string; footer_banner_url?: string; }
export interface OutreachTemplate { id: number; name: string; subject?: string; body: string; category?: string; is_default?: boolean; created_at?: string; }
export interface EmailRecord { id: number; lead_id: number; subject?: string; body?: string; html_body?: string; header_image_url?: string; signature_template_id?: number; outreach_template_id?: number; outreach_template_name?: string; status?: string; to_email?: string; sent_at?: string; opened_at?: string; replied_at?: string; gmail_message_id?: string; error_message?: string; full_name?: string; designation?: string; department?: string; company?: string; sender_email?: string; phone?: string; website?: string; linkedin?: string; address?: string; logo_url?: string; digital_signature_url?: string; footer_banner_url?: string; }
export interface Reply { id: number; lead_id: number; content?: string; intent?: string; sentiment?: string; received_at?: string; processed?: boolean; lead_status?: string; }
export interface Contact { id: number; first_name?: string; last_name?: string; email: string; phone?: string; title?: string; linkedin_url?: string; }
export interface Company { id: number; name: string; domain?: string; industry?: string; website?: string; org_type?: string; state?: string; city?: string; country?: string; employee_size?: string; }
export interface LeadFullDetail { lead: Lead; company?: Company; contact?: Contact; signals: Signal[]; emails: EmailRecord[]; calls: Call[]; activities: Activity[]; notes: Note[]; meetings: Meeting[]; }
export interface AgentStatus { name: string; key: string; status: string; last_run?: string; next_run?: string; last_result?: string; }
export interface PipelineReport { lead_funnel: Record<string, number>; pipeline_forecast: { total_value: number; weighted_value: number; close_probability: number; }; revenue_forecast: { expected_revenue: number; forecast_period: string; }; risk_flags: string[]; stalled_deals: string[]; campaign_performance: { sent: number; opened: number; clicked: number; replied: number; }; conversion_rate: { outreach_to_reply: number; reply_to_meeting: number; meeting_to_close: number; }; next_best_actions: string[]; }

export interface AICompanySummary { company_overview?: string; business_model?: string; industry?: string; current_priorities?: string; business_goals?: string; technology_focus?: string; healthcare_focus?: string; ai_initiatives?: string; digital_transformation?: string; recent_initiatives?: string; expansion_plans?: string; global_presence?: string; research_programs?: string; hiring_activity?: string; potential_challenges?: string; possible_opportunities?: string; buying_signals_detected?: string; }
export interface WebsiteInsight { page_type: string; page_url?: string; page_title?: string; scraped_at?: string; }
export interface LinkedinInsight { post_type?: string; headline?: string; source_url?: string; published_date?: string; }
export interface NewsInsight { event_type?: string; headline?: string; source_name?: string; source_url?: string; published_date?: string; relevance_score?: number; }
export interface CompanyIntelligenceOut { id: number; company_id: number; status: string; last_refreshed_at?: string; company_website?: string; ai_summary?: AICompanySummary; website_insights: WebsiteInsight[]; linkedin_insights: LinkedinInsight[]; news_insights: NewsInsight[]; }

// ── Agent Controller types ─────────────────────────────────────────────────────
export interface AgentGoal {
  id?: number;
  target_metric: 'meetings_booked' | 'leads_qualified' | 'replies_received' | 'leads_persisted';
  target_value: number;
  current_value?: number;
  period: 'weekly' | 'daily';

  min_sample_for_revision: number;
  reply_rate_floor: number;
  reflect_every_n_cycles: number;
  auto_rescan_signals: boolean;
  auto_re_enrich_lead: boolean;
  auto_revise_template: boolean;
  auto_book_meeting: boolean;

  /** Controls how the controller selects the outreach template each cycle */
  outreach_strategy?: 'fixed' | 'rotate' | 'ai_select';

  updated_at?: string;
}


export interface AgentDecision {
  id: number;
  cycle_id: string;
  chosen_action: string;
  action_params?: Record<string, unknown>;
  reasoning?: string;
  status: 'pending_approval' | 'executed' | 'approved' | 'skipped' | 'failed';
  outcome?: Record<string, unknown>;
  error_detail?: string;
  goal_progress?: { current: number; target: number; pct: number; on_track: boolean };
  created_at: string;
  executed_at?: string;
}

export interface AgentReflection {
  id: number;
  lesson: string;
  tags?: Record<string, string | number | null>;
  episode_cycle_ids?: string[];
  created_at: string;
}
