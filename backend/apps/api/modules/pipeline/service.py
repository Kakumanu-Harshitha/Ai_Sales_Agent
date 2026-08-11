"""
Pipeline module — orchestrates repository queries into a complete pipeline report.
Generates next_best_actions recommendations based on computed data.
"""

import logging
from sqlalchemy.orm import Session
from .repository import PipelineRepository
from .schemas import (
    PipelineReportResponse, LeadFunnel, PipelineForecast,
    RevenueForecast, CampaignPerformance, ConversionRate,
)

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self):
        self.repo = PipelineRepository()

    def generate_report(self, db: Session) -> PipelineReportResponse:
        """
        Aggregate all pipeline data from PostgreSQL and return
        the full PipelineReport matching the schema contract.
        """
        # Gather all data
        funnel_data = self.repo.get_lead_funnel(db)
        stalled = self.repo.get_stalled_deals(db)
        risks = self.repo.get_risk_flags(db)
        campaign = self.repo.get_campaign_performance(db)
        forecast = self.repo.get_pipeline_forecast(db)
        revenue = self.repo.get_revenue_forecast(db)
        conversion = self.repo.get_conversion_rates(db)

        # Generate next best actions based on the data
        actions = self._compute_next_best_actions(
            funnel_data, stalled, risks, campaign, conversion
        )

        return PipelineReportResponse(
            lead_funnel=LeadFunnel(**funnel_data),
            pipeline_forecast=PipelineForecast(**forecast),
            revenue_forecast=RevenueForecast(**revenue),
            risk_flags=risks,
            stalled_deals=stalled,
            campaign_performance=CampaignPerformance(**campaign),
            conversion_rate=ConversionRate(**conversion),
            next_best_actions=actions,
        )

    def _compute_next_best_actions(
        self, funnel: dict, stalled: list, risks: list,
        campaign: dict, conversion: dict
    ) -> list[str]:
        """
        Rule-based next best action recommendations.
        In production, the Pipeline Intelligence Agent (OpenRouter)
        would generate these. This provides sensible defaults.
        """
        actions = []

        # Check for stalled deals
        if len(stalled) > 0:
            actions.append(
                f"Follow up on {len(stalled)} stalled deal(s) that have been "
                f"stuck in the same stage for over 14 days."
            )

        # Check for at-risk leads
        if len(risks) > 0:
            actions.append(
                f"Re-engage {len(risks)} lead(s) with no activity in 10+ days "
                f"before they go cold."
            )

        # Low reply rate
        if campaign.get("sent", 0) > 0:
            reply_rate = (campaign.get("replied", 0) / campaign["sent"]) * 100
            if reply_rate < 10:
                actions.append(
                    f"Email reply rate is {reply_rate:.1f}%. Consider A/B testing "
                    f"subject lines and personalizing outreach with stronger signals."
                )

        # Pipeline has no deals
        total_open = sum(
            funnel.get(s, 0) for s in
            ["scored", "contacted", "replied", "meeting_booked", "proposal_sent"]
        )
        if total_open == 0:
            actions.append(
                "Pipeline is empty. Run the Prospecting Agent to discover new leads."
            )

        # Lots of new leads not scored
        new_count = funnel.get("new", 0)
        if new_count > 5:
            actions.append(
                f"{new_count} new leads have not been scored. "
                f"Run signal detection to prioritize outreach."
            )

        # Low meeting conversion
        if conversion.get("reply_to_meeting", 0) < 20 and funnel.get("replied", 0) > 0:
            actions.append(
                "Reply-to-meeting conversion is below 20%. "
                "Improve your call-to-action and offer clearer meeting scheduling."
            )

        # Fallback if everything looks good
        if not actions:
            actions.append(
                "Pipeline health is good. Continue current outreach cadence "
                "and monitor for new buying signals."
            )

        return actions
