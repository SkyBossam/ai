"""Guard platform selection without installing training frameworks on a Pi."""
from pathlib import Path
import unittest
from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT=Path(__file__).resolve().parents[1]


def selected(machine,python,system):
    env=default_environment()
    env.update(platform_machine=machine,python_version=python,python_full_version=python+'.0',
               sys_platform='win32' if system=='Windows' else 'linux',platform_system=system)
    values={}
    for line in (ROOT/'requirements.txt').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        req=Requirement(line)
        if req.marker is None or req.marker.evaluate(env):
            if req.name in values:raise AssertionError('Duplicate active requirement: '+req.name)
            values[req.name]=req
    return values


class RequirementTests(unittest.TestCase):
    def test_arm_devices_do_not_install_pc_training_frameworks(self):
        for machine,python in [('armv7l','3.9'),('aarch64','3.11'),('aarch64','3.12')]:
            with self.subTest(machine=machine,python=python):
                packages=selected(machine,python,'Linux')
                for name in ('ultralytics','tensorflow','tensorflow-hub','roboflow','opensmile'):
                    self.assertNotIn(name,packages)
                if machine=='armv7l':
                    self.assertIn('ncnn',packages)
                    self.assertIn('tflite-runtime',packages)
                    self.assertNotIn('onnxruntime',packages)
                else:
                    self.assertIn('onnxruntime',packages)
                    self.assertNotIn('opencv-python',packages)  # Provided by apt.

    def test_pc_uses_object_training_version_and_supported_tensorflow(self):
        for machine,system in [('AMD64','Windows'),('x86_64','Linux')]:
            for python in ('3.11','3.12'):
                with self.subTest(machine=machine,python=python):
                    packages=selected(machine,python,system)
                    self.assertEqual(str(packages['ultralytics'].specifier),'==8.4.176')
                    self.assertEqual('tensorflow' in packages,python=='3.11')
                    self.assertEqual('tensorflow-hub' in packages,python=='3.11')
                    self.assertNotIn('tflite-runtime',packages)
                    self.assertNotIn('ncnn',packages)

    def test_legacy_lists_are_removed(self):
        for name in ('requirements-train.txt','requirements-pi.txt','requirements-edge.txt',
                     'requirements-posture-train.txt','requirements-cry-simulation.txt',
                     'training/objects/requirements.txt','deploy/pi/requirements-usb.txt','deploy/pi/requirements-csi.txt'):
            self.assertFalse((ROOT/name).exists(),name)


if __name__=='__main__':unittest.main()
