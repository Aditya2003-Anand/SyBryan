from django.contrib import admin
from .models import ContentDB,OAuthToken,WeeklySelection,MetaPageDB,ScheduleContentDB

# Register your models here.
admin.site.register(ContentDB)
admin.site.register(OAuthToken)
admin.site.register(WeeklySelection)
admin.site.register(MetaPageDB)
admin.site.register(ScheduleContentDB)


