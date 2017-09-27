# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2017-09-05 09:06
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import jsonfield.fields
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Panel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(help_text='The display name of the panel, visible to panel members.', max_length=150)),
                ('welcome_message', models.TextField(blank=True, help_text='Welcome text to show on invitations.')),
                ('contact_info', models.CharField(help_text='How panel members should contact you with questions.', max_length=500)),
                ('consent_text', models.CharField(help_text='Disclaimer shown to panel members about how information will be used.', max_length=500)),
                ('private_notes', models.TextField(blank=True, help_text='Private notes for the panel owner.')),
                ('extra', jsonfield.fields.JSONField(blank=True, default={}, help_text='Additional information stored with this object.')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated', models.DateTimeField(auto_now=True, db_index=True)),
                ('admins', models.ManyToManyField(help_text='The users who own this panel.', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='PanelInvitation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.UUIDField(default=uuid.uuid4, editable=False, help_text='The invitation code used in the return URL.')),
                ('extra', jsonfield.fields.JSONField(blank=True, default={}, help_text='Additional information stored with this object.')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated', models.DateTimeField(auto_now=True, db_index=True)),
                ('panel', models.ForeignKey(help_text='The panel that the user is being invited to.', on_delete=django.db.models.deletion.CASCADE, to='userpanels.Panel')),
            ],
        ),
        migrations.CreateModel(
            name='PanelMembership',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invitation_code', models.UUIDField(editable=False, help_text='The invitation code used to accept the invitation.')),
                ('extra', jsonfield.fields.JSONField(blank=True, default={}, help_text='Additional information stored with this object.')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated', models.DateTimeField(auto_now=True, db_index=True)),
                ('panel', models.ForeignKey(help_text='The panel that the user is a member of.', on_delete=django.db.models.deletion.CASCADE, to='userpanels.Panel')),
                ('user', models.ForeignKey(help_text='The user who is a member of the panel.', on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='panelmembership',
            unique_together=set([('panel', 'user')]),
        ),
    ]