# Generated by Django 3.2.25 on 2025-04-15 16:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('announcements', '0035_auto_20250205_1552'),
    ]

    operations = [
        migrations.AlterField(
            model_name='announcement',
            name='public',
            field=models.BooleanField(default=False, help_text='Restricted activities have announcements that are only visible to members of the activity. Enabling this will make the announcement visible to all users.'),
        ),
        migrations.AlterField(
            model_name='historicalannouncement',
            name='public',
            field=models.BooleanField(default=False, help_text='Restricted activities have announcements that are only visible to members of the activity. Enabling this will make the announcement visible to all users.'),
        ),
    ]
