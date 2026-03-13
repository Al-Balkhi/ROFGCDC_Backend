"""
reports/services.py

Business-logic layer for citizen-report workflows.

Keeping domain logic out of views makes it:
  - Independently unit-testable (no HTTP layer needed).
  - Reusable across multiple view actions.
  - Easier to extend (e.g. async task queue, admin CLI).
"""
import logging
from datetime import date

from django.contrib.gis.db.models.functions import Distance

from optimization.models import Bin, Scenario
from optimization.services import solve_vrp

logger = logging.getLogger(__name__)


def create_immediate_plan(report, created_by, name_prefix: str = "") -> Scenario:
    """
    Create a same-day collection Scenario for a citizen Report.

    Selects the municipality's first available vehicle and landfill,
    finds the closest active bin to the report location, creates the
    Scenario, then asynchronously triggers the VRP solver to generate
    route geometry.

    Args:
        report:       The Report model instance to handle.
        created_by:   The User (planner or admin) initiating the plan.
        name_prefix:  Optional string prefix for the scenario name.
                      Defaults to "Immediate Plan".

    Returns:
        The newly created Scenario instance (status=IN_PROGRESS).

    Raises:
        ValueError: When the municipality has no vehicle or no landfill
                    assigned, making plan generation impossible.
    """
    municipality = report.municipality
    if not municipality:
        raise ValueError("No municipality assigned to this report.")

    vehicle = municipality.vehicles.first()
    landfill = municipality.landfills.first()

    if not vehicle:
        raise ValueError("No vehicles available in this municipality.")
    if not landfill:
        raise ValueError("No landfills available in this municipality.")

    prefix = name_prefix.strip() or "Immediate Plan"
    scenario = Scenario.objects.create(
        name=f"{prefix} for Report {report.id}",
        description=f"Auto-generated plan for citizen report {report.id}.",
        municipality=municipality,
        start_location=municipality.hq_location,
        collection_date=date.today(),
        vehicle=vehicle,
        end_landfill=landfill,
        status=Scenario.Status.IN_PROGRESS,
        created_by=created_by,
    )

    # Add the closest active bin to the scenario.
    closest_bin = (
        Bin.objects.filter(municipality=municipality, is_active=True)
        .annotate(distance=Distance('location', report.location))
        .order_by('distance')
        .first()
    )
    if closest_bin:
        scenario.bins.add(closest_bin)

    # Trigger VRP solver — failure is non-fatal: the scenario is still
    # created and dispatchers can re-solve manually.
    try:
        solve_vrp(scenario.id)
    except Exception as exc:
        logger.error(
            "VRP solver failed for auto-generated scenario %s (report %s): %s",
            scenario.id, report.id, exc,
            exc_info=True,
        )

    return scenario
