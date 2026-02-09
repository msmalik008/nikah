from django.core.cache import cache
from django.db.models import QuerySet
import json
from datetime import datetime


def cache_simple_data(key, data, timeout=300):
    """
    Cache only simple, picklable data.
    Converts complex objects to simple dicts/lists.
    """
    # Convert data to picklable format
    picklable_data = convert_to_picklable(data)
    cache.set(key, picklable_data, timeout)
    return picklable_data


def get_cached_simple_data(key):
    """Get cached simple data"""
    return cache.get(key)


def convert_to_picklable(obj):
    """
    Convert complex objects to simple picklable structures.
    """
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [convert_to_picklable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_to_picklable(value) for key, value in obj.items()}
    elif isinstance(obj, QuerySet):
        # Convert QuerySet to list of dicts
        result = []
        for item in obj:
            result.append(convert_model_to_dict(item))
        return result
    elif hasattr(obj, '__dict__'):
        # Convert model instances to dicts
        return convert_model_to_dict(obj)
    elif hasattr(obj, 'isoformat'):  # datetime objects
        return obj.isoformat()
    else:
        # For any other type, try to convert to string
        try:
            return str(obj)
        except:
            return None


def convert_model_to_dict(instance):
    """Convert a model instance to a simple dictionary"""
    if instance is None:
        return None
    
    data = {}
    for field in instance._meta.fields:
        field_name = field.name
        value = getattr(instance, field_name)
        
        # Convert special types
        if hasattr(value, 'url'):  # FileField, ImageField
            data[field_name] = value.url if value else None
        elif hasattr(value, 'isoformat'):  # datetime
            data[field_name] = value.isoformat()
        elif hasattr(value, '__dict__'):  # related object
            # Don't go too deep, just get the ID
            data[f'{field_name}_id'] = value.id if hasattr(value, 'id') else None
        else:
            data[field_name] = value
    
    # Add common useful attributes
    if hasattr(instance, 'id'):
        data['id'] = instance.id
    
    if hasattr(instance, 'username'):
        data['username'] = instance.username
    
    if hasattr(instance, 'get_absolute_url'):
        data['url'] = instance.get_absolute_url()
    
    return data