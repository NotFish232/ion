# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-04-13 23:29
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL),]

    operations = [
        migrations.CreateModel(
            name='FoundItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=100)),
                ('description', models.TextField(max_length=1000)),
                ('found', models.DateField()),
                ('added', models.DateTimeField(auto_now_add=True)),
                ('retrieved', models.BooleanField(default=False)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-added'],},),
        migrations.CreateModel(
            name='LostItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=100)),
                ('description', models.TextField(max_length=1000)),
                ('last_seen', models.DateField()),
                ('added', models.DateTimeField(auto_now_add=True)),
                ('found', models.BooleanField(default=False)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-added'],},),
    ]
