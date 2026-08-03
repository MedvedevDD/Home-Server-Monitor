"""Tests for the Core Services lifecycle."""
from __future__ import annotations
import unittest
from core.discovery import Availability, Capability, ProviderDiscovery
from core.events import Event, EventBus
from core.health import summarize_health
from core.manager import CollectorManager
from core.pipeline import MetricsPipeline
from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from metric import Metric

class Ready(Provider):
    name='ready'; domain='hardware'; capabilities=('smart',)
    def collect(self): return ProviderResult(self.name, metrics=[Metric('x',fields={'v':1})])
class Dependent(Provider):
    name='dependent'; dependencies=('ready',)
    def collect(self): return ProviderResult(self.name)
class Missing(Provider):
    name='missing'; dependencies=('absent',)
    def collect(self): raise AssertionError('must not run')
class BrokenDiscovery(Provider):
    name='broken'
    def discover(self): raise RuntimeError('discovery failed')
    def collect(self): raise AssertionError('must not run')
class Warning(Provider):
    name='warning'
    def collect(self): return ProviderResult(self.name,warnings=[ProviderMessage(self.name,'warn')])

class CoreServicesTests(unittest.TestCase):
    def test_dependencies_and_discovery(self):
        runs=CollectorManager([Ready(),Dependent(),Missing(),BrokenDiscovery()]).discover()
        self.assertEqual(runs[0].discovery.availability,Availability.READY)
        self.assertEqual(runs[1].discovery.availability,Availability.READY)
        self.assertEqual(runs[2].discovery.availability,Availability.SKIPPED)
        self.assertEqual(runs[3].discovery.availability,Availability.ERROR)
    def test_pipeline_exports_flat_metrics(self):
        runs=CollectorManager([Ready()]).collect(); written=[]
        count=MetricsPipeline(lambda metrics: written.extend(metrics)).export(runs)
        self.assertEqual(count,1); self.assertEqual(written[0].measurement,'x')
    def test_health_summary(self):
        summary=summarize_health(CollectorManager([Ready(),Warning()]).collect())
        self.assertEqual(summary.status,'warning'); self.assertEqual(summary.score,95)
    def test_event_bus(self):
        events=[]; bus=EventBus(); bus.subscribe(events.append)
        bus.publish(Event('test','unit','info','hello'))
        self.assertEqual(events[0].message,'hello')
