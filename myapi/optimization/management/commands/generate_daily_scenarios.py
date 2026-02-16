from django.core.management.base import BaseCommand
from django.utils import timezone

from optimization.models import Scenario, ScenarioTemplate


class Command(BaseCommand):
    help = 'Generate daily scenarios from active recurring templates.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        weekday = str(today.weekday())

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
            created_count += 1

        self.stdout.write(self.style.SUCCESS(f'Generated {created_count} scenarios for {today}'))
