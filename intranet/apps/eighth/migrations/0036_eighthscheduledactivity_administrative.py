# -*- coding: utf-8 -*-
# Generated by Django 1.9.2 on 2016-03-12 02:39
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('eighth', '0035_eighthactivity_blacklist'),]

    operations = [migrations.AddField(
        model_name='eighthscheduledactivity',
        name='administrative',
        field=models.BooleanField(default=False),),]
