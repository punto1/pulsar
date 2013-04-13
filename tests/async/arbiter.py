'''Tests for arbiter and monitors.'''
import os
import time
from threading import current_thread

import pulsar
from pulsar import send, spawn, system, platform, ACTOR_ACTION_TIMEOUT,\
                    multi_async
from pulsar.utils.pep import default_timer
from pulsar.apps.test import unittest, run_on_arbiter, ActorTestMixin,\
                                dont_run_with_thread


def timeout(start):
    return default_timer() - start > 1.5*ACTOR_ACTION_TIMEOUT


class BogusActor(pulsar.Actor):
    
    def notify(self):
        #This actor does not send notify messages to the arbiter
        if not self.params.last_notified:
            super(BogusActor, self).notify()
        else:
            pass
    
    def stop(self, force=False, exit_code=0):
        # override stop method so that no stopping can take place
        pass
    
    
class TestArbiterThread(ActorTestMixin, unittest.TestCase):
    concurrency = 'thread'

    @run_on_arbiter
    def testArbiterObject(self):
        '''Test the arbiter in its process domain'''
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        self.assertEqual(arbiter.impl.kind, 'monitor')
        self.assertTrue(arbiter.monitors)
        self.assertEqual(arbiter.exit_code, None)
        info = arbiter.info()
        self.assertTrue('server' in info)
        server = info['server']
        self.assertEqual(server['state'], 'running')
        
    @run_on_arbiter
    def test_registered(self):
        '''Test the arbiter in its process domain'''
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        self.assertTrue(arbiter.registered)
        self.assertTrue('arbiter' in arbiter.registered)
        self.assertTrue('test' in arbiter.registered)
    
    @run_on_arbiter
    def test_ping_test_worker(self):
        arbiter = pulsar.get_actor()
        info = arbiter.info()
        test = info['monitors']['test']
        workers = [w['actor']['actor_id'] for w in test['workers']]
        self.assertTrue(workers)
        result = yield multi_async((arbiter.send(w, 'ping') for w in workers))
        self.assertEqual(len(result), len(workers))
        self.assertEqual(result, len(result)*['pong'])
        
    @run_on_arbiter
    def testSpawning(self):
        arbiter = pulsar.get_actor()
        self.assertEqual(arbiter.name, 'arbiter')
        self.assertTrue(len(arbiter.monitors) >= 1)
        future = spawn(name='testSpawning', concurrency=self.concurrency)
        self.assertTrue(future.aid in arbiter.managed_actors)
        yield future
        proxy = future.result
        self.assertEqual(future.aid, proxy.aid)
        self.assertEqual(proxy.name, 'testSpawning')
        self.assertTrue(proxy.aid in arbiter.managed_actors)
        yield send(proxy, 'stop')
        
    @run_on_arbiter
    def testBadMonitor(self):
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.monitors)
        name = list(arbiter.monitors.values())[0].name
        self.assertRaises(KeyError, arbiter.add_monitor, pulsar.Monitor, name)
        
    @run_on_arbiter
    def testTimeout(self):
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        proxy = yield self.spawn(actor_class=BogusActor, name='foo', timeout=1)
        self.assertEqual(proxy.name, 'foo')
        self.assertTrue(proxy.aid in arbiter.managed_actors)
        proxy = arbiter.managed_actors[proxy.aid]
        #self.assertEqual(proxy.stopping_start, None)
        time.sleep(1.5)
        self.assertTrue(arbiter.manage_actors())
        self.assertTrue(proxy.stopping_start)
        while not timeout(proxy.stopping_start) and proxy.aid in arbiter.managed_actors:
            yield pulsar.NOT_DONE
            arbiter.manage_actors()
        self.assertFalse(proxy.aid in arbiter.managed_actors)
        thread_actors = pulsar.process_local_data('thread_actors')
        self.assertFalse(proxy.aid in thread_actors)
        
    @run_on_arbiter
    def testTerminate(self):
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        proxy = yield self.spawn(actor_class=BogusActor, name='foo', timeout=1)
        self.assertEqual(proxy.name, 'foo')
        proxy = arbiter.managed_actors[proxy.aid]
        #self.assertEqual(proxy.stopping_start, None)
        time.sleep(1.5)
        n = arbiter.manage_actors()
        self.assertTrue(n)
        self.assertTrue(proxy.stopping_start)
        while not timeout(proxy.stopping_start) and proxy.aid in arbiter.managed_actors:
            yield pulsar.NOT_DONE
            arbiter.manage_actors()
        thread_actors = pulsar.process_local_data('thread_actors')
        self.assertFalse(proxy.aid in thread_actors)
    
    @unittest.skipUnless(platform.is_posix, 'For posix systems only')
    @run_on_arbiter
    def testFakeSignal(self):
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        # Now put the signal in the queue
        arbiter.signal_queue.put('foooooo')
        self.assertTrue(arbiter.signal_queue.qsize() >= 1)
        # we need to yield so that the arbiter has a chance to process the signal
        yield pulsar.NOT_DONE
        # The arbiter should have processed the fake signal
        #TODO this is not valid in multiprocessing!
        #self.assertEqual(arbiter.signal_queue.qsize(), 0)
    
    @unittest.skipUnless(platform.is_posix, 'For posix systems only')    
    @run_on_arbiter
    def testSignal(self):
        arbiter = pulsar.get_actor()
        self.assertTrue(arbiter.is_arbiter())
        for sig in system.SIG_NAMES:
            if sig not in system.EXIT_SIGNALS:
                break
        # send the signal
        arbiter.signal_queue.put(sig)
        self.assertTrue(arbiter.signal_queue.qsize() >= 1)
        yield pulsar.NOT_DONE
        #TODO this is not valid in multiprocessing!
        #self.assertEqual(arbiter.signal_queue.qsize(), 0)
        
    def test_no_arbiter_in_worker_domain(self):
        worker = pulsar.get_actor()
        self.assertEqual(pulsar.arbiter(), None)
        self.assertTrue(worker.monitor)
        self.assertNotEqual(worker.monitor.name, 'arbiter')

@dont_run_with_thread
class TestArbiterProcess(TestArbiterThread):
    impl = 'process'  