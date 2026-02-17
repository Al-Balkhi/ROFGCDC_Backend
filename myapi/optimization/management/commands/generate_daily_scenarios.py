from django.core.management.base import BaseCommand
from django.utils import timezone
from optimization.models import Scenario, ScenarioTemplate
from optimization.services import VRPSolver


class Command(BaseCommand):
    help = 'Generate daily scenarios from active recurring templates.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Date in YYYY-MM-DD format to generate scenarios for.')

    def handle(self, *args, **options):
        date_str = options.get('date')
        if date_str:
            from datetime import datetime
            today = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            today = timezone.localdate()
            
        # Mapping Python weekday (Mon=0) to our system index (Sat=0)
        # Mon(0)->2, Tue(1)->3, Wed(2)->4, Thu(3)->5, Fri(4)->6, Sat(5)->0, Sun(6)->1
        weekday = str((today.weekday() + 2) % 7)

        templates = ScenarioTemplate.objects.filter(is_active=True)
        created_count = 0

        for template in templates:
            allowed_days = {d.strip() for d in template.weekdays.split(',') if d.strip()}
            if weekday not in allowed_days:
                continue

            if Scenario.objects.filter(
                generated_from_template=template,
                collection_date=today,
            ).exists():
                continue

            scenario = Scenario.objects.create(
                name=f"{template.name} - {today}",
                description='Generated automatically from recurring template',
                municipality=template.municipality,
                vehicle=template.vehicle,
                end_landfill=template.end_landfill,
                collection_date=today,
                created_by=template.created_by,
                generated_from_template=template,
            )
            scenario.bins.set(template.bins.all())
            
            # Trigger solver automatically for generated plans
            try:
                VRPSolver(scenario.id).run()
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to solve scenario {scenario.id}: {str(e)}"))
                
            created_count += 1

        self.stdout.write(self.style.SUCCESS(f'Generated {created_count} scenarios for {today}'))
