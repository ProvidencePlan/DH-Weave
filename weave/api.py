import logging
from weave.models import *
from django.conf import settings

log = logging.getLogger('datahub.indicator')

WEAVE_SETTINGS = getattr(settings, "WEAVE", {})
WEAVE_CONNECTION = getattr(WEAVE_SETTINGS, 'CONNECTION', "portal_db")


def get_or_create_data_table(tbl_name):
    """ get or create a new data table into Weave Meta info
        Returns an entity_id
        This should create
            1 HubEntityIndex
            1 WeaveManifest
            4 WeaveMetaPrivate
            1 WeaveMetaPublic

    """
    sync_db_sequence()
    REQUIRED_PRIVATE_META = (
        ('importMethod', 'Portal Indicator'),
        ('sqlSchema', 'public'),
        ('sqlTable', 'indicator_indicatordata'),
        ('connection', WEAVE_CONNECTION ),
    )

    REQUIRED_PUBLIC_META = (
        ('title', tbl_name),
    )

    hei = HubEntityIndex()
    hei.save()

    try:
        # try to find a meta entry with this name, it may be what we are
        # looking for
        m = WeaveMetaPublic.objects.get(meta_name='title',meta_value=tbl_name, h_e_index__isnull=False)
        return m.entity_id

    except WeaveMetaPublic.DoesNotExist:

        w_manifest = WeaveManifest(h_e_index=hei, type_id=0) # data tables are always type_id=0
        w_manifest.save()

        # now we need to create required public/private sets of meta data for this Data
        # Table
        for pm in REQUIRED_PRIVATE_META:
            WeaveMetaPrivate(h_e_index=hei, entity_id=w_manifest.entity_id, meta_name=pm[0], meta_value=pm[1]).save()

        for pm in REQUIRED_PUBLIC_META:
            WeaveMetaPublic(h_e_index=hei, entity_id=w_manifest.entity_id, meta_name=pm[0], meta_value=pm[1]).save()

        return w_manifest.pk


def insert_data_row(parent_id, title, name, data_type, sql_query, object_id, year, key_type=None, data_table=None, min=None, max=None):
    #log.debug("parent id: %s, Title %s, key_Type: %s, data_table: %s" % (parent_id, title, key_type, data_table))
    """ Insert a data entity and create relationship to parent entity
        This should create
            1 HubEntityIndex
            1 Weave Manifest
            1 WeaveHeirchy
            5 WeaveMetaPrivate
            3 WeaveMetaPublic
    """
    sync_db_sequence()
    REQUIRED_PRIVATE_META = (
        ('sqlQuery', sql_query),
        ('sqlSchema', 'public'),
        ('sqlTable', 'indicator_indicatordata'),
        ('importMethod', 'Portal Indicator'),
        ('connection', WEAVE_CONNECTION ),

    )

    if data_type=="numeric":
        data_type = "number"

    REQUIRED_PUBLIC_META = (
        ('title', title), # the title
        ('name', name), # the indicator name
        ('dataType', data_type), # number or string
        ('object_id', object_id), # to ease the transition. In datahub this is our Indicator Id
        ('year', year),
        ('min', min or ''),
        ('max', max or ''),
        ('keyType', key_type),
    )

    if data_table is not None:
        REQUIRED_PUBLIC_META += (
            ('dataTable', data_table),
        )
    #log.debug(REQUIRED_PUBLIC_META)
    hei = HubEntityIndex()
    hei.save()

    # create an entry in weave_manifest
    m = WeaveManifest(h_e_index=hei, type_id=1)
    m.save()

    # create a relationship in hierarachy table
    count = WeaveHierarchy.objects.filter(parent_id=parent_id).count()
    WeaveHierarchy(h_e_index=hei, parent_id=parent_id, child_id=m.pk, sort_order=count+1).save()

    for pm in REQUIRED_PRIVATE_META:
        WeaveMetaPrivate(h_e_index=hei, entity_id=m.entity_id, meta_name=pm[0], meta_value=pm[1]).save()


    # kwargs for later use
    weave_flat_meta_kwargs = {
        'h_e_index':hei,
        'weaveEntityId':m.entity_id,
    }

    for pm in REQUIRED_PUBLIC_META:
        WeaveMetaPublic.objects.create(h_e_index=hei, entity_id=m.entity_id, meta_name=pm[0], meta_value=pm[1])
        weave_flat_meta_kwargs[pm[0]] = pm[1]

    # Using the kwargs we've collected, create a flat version of all the related weave meta public

    WeaveFlatPublicMeta.objects.create(**weave_flat_meta_kwargs)


def clear_generated_meta():
    """ Clear out all the weave meta generated by the the weave django app"""
    hubs = HubEntityIndex.objects.all()
    for h in hubs:
        rels = [rel.get_accessor_name() for rel in h._meta.get_all_related_objects()]
        for r in rels:
            objects = getattr(h, r).all().delete()
        h.delete()

def get_hierarchy_as_xml():
    """ Return weave data heirchy as xml categories. THIS IS NOT USED TODO:clean up test that include this"""
    out = u' '
    parent_ids = WeaveHierarchy.objects.all().distinct('parent_id')

    for p in parent_ids:
        p_meta = WeaveMetaPublic.objects.get(entity_id=p.parent_id, meta_name="title")
        xml = WeaveXMLSet(p_meta.meta_value, p.parent_id)
        # now add attibute nodes
        # get all the Heirarchy objects that belong to this parent id
        for h_obj in get_hierarchy_items(p.parent_id):
            xml.add_attribute(**h_obj)
        #out += xml.render()
    return out

def get_weave_item_as_dict(entity_id):
    """ Return a dict of related weave entity items """
    attribute = {}
    items = WeaveMetaPublic.objects.filter(entity_id=entity_id).distinct('meta_name').only('meta_value')
    attribute['weaveEntityId'] = entity_id
    for item in items:
        attribute[item.meta_name] = item.meta_value
    return attribute

def get_hierarchy_items(parent_id):
    for h_obj in WeaveHierarchy.objects.filter(parent_id=parent_id):
        title = WeaveMetaPublic.objects.get(entity_id=h_obj.child_id, meta_name="title").meta_value
        datatype = WeaveMetaPublic.objects.get(entity_id=h_obj.child_id, meta_name="dataType").meta_value
        y_kwargs = {
            'title':title,
            'datatype':datatype,
            'weave_entity_id':h_obj.child_id,
        }
        try:
            object_id = WeaveMetaPublic.objects.get(entity_id=h_obj.child_id, meta_name="object_id").meta_value
            y_kwargs['object_id'] = object_id
        except WeaveMetaPublic.DoesNotExist:
            pass

        yield y_kwargs

def get_custom_hierarchy_as_xml(title, hierarchy_list_items):
    """ Generate a custom hierarchy based on the the h_list_items
        the h_list_items should be a list of dicts that follow this ex:
        [{
            'title':'My thing',
            'datatype':'string or number',
            'weave_entity_id':<a proper weave entity>,
        }]
    """
    xml = WeaveXMLSet(title=title, weave_entity_id="99999")
    for item in hierarchy_list_items:
        xml.add_attribute(**item)
    return xml.render()



class WeaveXMLSet():
    def __init__(self, title, weave_entity_id):
        self.title = title
        self.weave_entity_id = weave_entity_id
        self.attributes = []

    def add_attribute(self, title, datatype, weave_entity_id=None, object_id=None):
        self.attributes.append({
            'title':title,
            'datatype':datatype,
            'weave_entity_id':weave_entity_id if weave_entity_id is not None else 0,
            'object_id': object_id or '0000'
        })

    def get_weave_entity_id(self, title):
        """ Look up a for realz weave entity id by title"""
        return WeaveMetaPublic.objects.get(meta_name='title', meta_value=title).entity_id

    def render(self):
        cat_head = u"""<category title="{0}" weaveEntityId="{1}" >""".format(self.title, self.weave_entity_id)
        cat_foot = u"""</category>"""
        attrs_nodes = u""
        for atr in self.attributes:
            node = u"""<attribute title="{title}" dataType="{datatype}" weaveEntityId="{weave_entity_id}" object_id="{object_id}"/>""".format(**atr)
            attrs_nodes += node + u"\n"

        return u"%s\n%s%s\n" % (cat_head, attrs_nodes, cat_foot)



# We are using a combination of Django and Weave to insert records into the
# weave Tables. Because we are doing that, we need to make sure to reset the
# squence from which automaticvalues are generated. We can use the management
# 'sqlsequencereset' to get the sql to do that, then pass that into a db cursor
# and execute it.

class Alf(object):
    pass


def sync_db_sequence():
    from django.core.management import call_command
    from django.db import connection
    import sys, StringIO, contextlib

    @contextlib.contextmanager
    def capture_stdout():
        old = sys.stdout
        capturer = StringIO.StringIO()
        sys.stdout = capturer
        data = Alf()
        yield data
        sys.stdout = old
        data.result = capturer.getvalue()

    with capture_stdout() as capture:
        call_command('sqlsequencereset', 'weave')
    cursor = connection.cursor()
    cursor.execute(capture.result)


