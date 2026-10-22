# Third-party licences and acknowledgements

HackEye is a free, open-source, **non-commercial** project. This repository's own code is under the
[Apache License 2.0](LICENSE). It builds on other people's work, and some of that work comes with
conditions that go beyond attribution. This file lists:

1. **What requires legal handling**: licences with obligations or restrictions that apply to anyone who
   uses, modifies or redistributes HackEye, and especially its models and app builds.
2. **Thanks**: the permissively licensed projects HackEye relies on, which only ask for attribution.

> This is a good-faith summary, not legal advice. The linked licence texts are what bind. If you fork
> HackEye for anything commercial, the items in section 1 will very likely stop you, or require
> separate licences.

Last reviewed: 2026-10-17. Sister repository: [HackEye-Models](https://github.com/brunoclpinto/HackEye-Models)
(training) has its own [THIRD_PARTY_LICENSES.md](https://github.com/brunoclpinto/HackEye-Models/blob/main/THIRD_PARTY_LICENSES.md).

---

## 1. Requires legal handling

| Component | Where it is used | Licence / terms | What it means for HackEye |
|---|---|---|---|
| **Ultralytics** (library and YOLO26 pretrained weights) | RnD rig (`ultralytics` package); every segmentation and detection model (`yolo26*-sem*` bases, the HackEye fine-tunes, `Apple/Models/YOLO/*.mlpackage`, `models/detector.pt`) | [AGPL-3.0](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) | Ultralytics treats models trained or fine-tuned with its library, and their exports (CoreML, ONNX), as covered by AGPL-3.0 unless an Ultralytics Enterprise licence is bought. **Anyone who receives an app build or model, or uses it over a network, must be able to get the complete corresponding source under AGPL-3.0.** The Apache-2.0 code here can be combined into an AGPL work, but a distributed app that bundles these models is effectively AGPL-3.0 as a whole. Note: App Store distribution terms and (A)GPL obligations are known to conflict (extra usage restrictions); check before publishing to the App Store. |
| **Mapillary Vistas v2.0** (dataset) | Training data of the HackEye segmentation models (in HackEye-Models; the data itself is not in this repository) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) plus Mapillary's research licence ([mapillary.com/dataset/vistas](https://www.mapillary.com/dataset/vistas)) | The data must not be redistributed; it is gitignored and only kept locally. The models trained on it should be used non-commercially, with attribution to Mapillary. Whether *ShareAlike* extends to trained weights is legally unsettled; HackEye takes the cautious reading and releases them under non-commercial, attribution-preserving terms only. |
| **Cityscapes** (dataset) | Ultralytics' `yolo26s-sem.pt`, the base of the app's earlier `yolo26s-semINT8512x896.mlpackage` | [Cityscapes terms of use](https://www.cityscapes-dataset.com/license/): non-commercial research, attribution and citation, no redistribution of the data | Derived models are for non-commercial use, with attribution. |
| **ADE20K** (dataset) | Ultralytics' `yolo26*-sem-ade20k.pt`, the warm-start checkpoints of the HackEye models | [ADE20K terms](https://groups.csail.mit.edu/vision/datasets/ADE20K/) (research and non-commercial use; images carry their own rights) | Non-commercial use, with attribution and citation (Zhou et al., *Scene Parsing through ADE20K Dataset*, CVPR 2017). |
| **UniDepth v2** (code and `unidepth-v2-vits14` weights) | RnD Lab depth option `unidepth-v2-s` | [CC BY-NC 4.0](https://github.com/lpiccinelli-eth/UniDepth/blob/main/LICENSE) | Non-commercial only. Give attribution (Piccinelli et al., *UniDepthV2*) and indicate changes. It can't be relicensed under Apache-2.0: if it ships in the app, its weights keep CC BY-NC 4.0 and forks can't use it commercially. |
| **Virtual KITTI 2** (dataset) | Fine-tuning data of Depth Anything V2 *Metric Outdoor Small* (Lab depth option `da2-metric-outdoor-small`) | [CC BY-NC-SA 3.0](https://europe.naverlabs.com/research/computer-vision/proxy-virtual-worlds-vkitti-2/) | The model itself is Apache-2.0 from its authors (see section 2). The data it was fine-tuned on is non-commercial, so HackEye treats the model as non-commercial too. |
| **Meta Wearables Device Access Toolkit** (`meta-wearables-dat-ios`, MWDATCore) | iOS app, Meta glasses camera (`Apple/Cameras/Meta/`) | [Meta Wearables Developer Terms](https://wearables.developer.meta.com/terms) and [Acceptable Use Policy](https://wearables.developer.meta.com/acceptable-use-policy): proprietary, not open source | Fetched through Swift Package Manager, never vendored here. Everyone who builds the app accepts Meta's terms themselves. The SDK is not covered by this repository's licence. |
| **GPL-3.0 tools in the RnD Docker image**: `evo`, `plyfile` (pulled in by Depth Anything 3's imports), and Ubuntu's `ffmpeg` (built with `--enable-gpl`) | RnD rig and Lab only (proxy videos, an unused DA3 export path). Not part of the iOS app | [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html) (ffmpeg: GPL build) | Only matters if someone redistributes the built `hackeye-rnd` image: then the GPL source offer applies to those components. Nothing in this repository links them into distributed software. |
| **Apple SDKs** (CoreML, Vision, AVFoundation, SwiftUI…) | iOS app | [Apple Developer Program License Agreement](https://developer.apple.com/support/terms/) | Standard platform terms for building and shipping iOS apps. |

### Checklist when shipping an app build or model
- [ ] Publish the complete source of that build (this repository and HackEye-Models at the matching commit), as AGPL-3.0 requires, and link it from the app.
- [ ] Credit Ultralytics, Mapillary Vistas, ADE20K/Cityscapes and every bundled model in the app's "About / Licences" screen.
- [ ] Bundle no CC BY-NC model (UniDepth) in any build that is sold, ad-supported or otherwise commercial. HackEye builds are free.
- [ ] Don't redistribute any dataset.
- [ ] Keep Meta's SDK under Meta's terms; don't vendor it.

---

## 2. Thanks

These projects are permissively licensed (Apache-2.0, MIT, BSD). They only ask for attribution, and HackEye
gratefully gives it:

**Depth models**
- **Depth Anything 3** (ByteDance Seed): code and the DA3-Small / DA3-Base weights, Apache-2.0. Used in
  the Lab depth pass. The DA3 Metric Large weights (also Apache-2.0) were used as the Lab reference.
- **Depth Anything V2**: the *Metric Outdoor Small* weights, Apache-2.0 (dataset note in section 1).

**Machine learning and vision**
- **PyTorch** and **torchvision**: BSD-3-Clause.
- **NumPy**: BSD-3-Clause.
- **SciPy**: BSD-3-Clause.
- **OpenCV** (`opencv-python-headless`): Apache-2.0.
- **ONNX Runtime**: MIT.
- **Pillow**: MIT-CMU.
- **imageio**: BSD-2-Clause.
- **pycolmap**: BSD-3-Clause.
- **trimesh**: MIT.
- **einops**: MIT.
- **Hugging Face** `huggingface_hub`, `safetensors` and `transformers` (loads Depth Anything V2): Apache-2.0.
- **timm** (PyTorch Image Models, used by UniDepth): Apache-2.0.

**Lab web stack**
- **FastAPI**: MIT.
- **Starlette**, **Uvicorn** and **httpx**: BSD-3-Clause.
- **Pydantic**: MIT.

**Tooling**
- **OmegaConf**: BSD-3-Clause.
- **addict**, **moviepy** and **polars**: MIT.
- **wandb** (imported by UniDepth's code; disabled with `WANDB_MODE=disabled` in the containers, so nothing is logged or sent): MIT.
- **PyYAML**: MIT.

**Testing**
- **pytest**: MIT.
- **Playwright**: Apache-2.0.

**Base images**
- `pytorch/pytorch` and Microsoft's Playwright images, under their projects' licences.

Thank you to all their authors and maintainers.

Licences were read from the installed packages' metadata (`importlib.metadata`) in the `hackeye-rnd`
image and from the model cards. If you spot a mistake, please open an issue.
