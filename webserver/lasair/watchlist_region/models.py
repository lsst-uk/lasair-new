from django.db import models
from django.contrib.auth.models import User


class Areas(models.Model):
    """Areas.
    """

    ar_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, models.DO_NOTHING, db_column='user', blank=True, null=True)
    name = models.CharField(max_length=256, blank=True, null=True)
    description = models.CharField(max_length=4096, blank=True, null=True)
    moc = models.TextField(blank=True, null=True)
    mocimage = models.TextField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)
    public = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now=True, editable=False, blank=True, null=True)

    class Meta:
        """Meta.
        """

        managed = True
        db_table = 'areas'

    def __str__(self):
        return self.user.first_name + ' ' + self.user.last_name + ': ' + self.name
