# EDLD Release Signing

Every EDLD release is signed, and so is every commit and tag. Releases are
signed by Indevlin's release key, in GitHub Actions; commits and tags by the
maintainer who made them.

---

## Verifying a release artefact

A release on the [releases page](https://github.com/indevlin/EDLD/releases)
carries seven files: five artefacts, a checksum manifest listing all five, and
one detached signature over that manifest.

| File | Contents |
|------|----------|
| `EDLD-<version>-linux-x86_64.tar.gz` | Linux binary |
| `EDLD-<version>-windows-x86_64.zip` | Windows binary |
| `EDLD-<version>-macos-arm64.zip` | macOS binary |
| `EDLD-<version>-server-linux-x86_64.tar.gz` | EDLD-server, Linux ([SERVER.md](SERVER.md)) |
| `EDLD-<version>-server-windows-x86_64.zip` | EDLD-server, Windows |
| `EDLD-<version>.sha256` | SHA-256 of all five, one per line |
| `EDLD-<version>.sha256.sig` | SSH signature over that manifest |

GitHub also attaches its own *Source code (zip)* and *Source code (tar.gz)* to
every release, generated from the tag. Those are the source download. They are
produced by GitHub rather than by the release workflow, so they are not part of
the manifest and carry no signature of ours. To obtain source you can verify,
clone the repository and check the signed tag — see
[Signed commits and tags](#signed-commits-and-tags).

The artefacts are not signed individually. The manifest names each one by
digest and the manifest itself is signed, so a valid signature plus a matching
digest gives the same guarantee for any file, and one signature check covers
the whole release. Verification is therefore two steps:

1. The signature on `EDLD-<version>.sha256` is valid for a key in
   `signing/allowed_signers`, under the identity `indevlin-vcs@indevlin.com`.
2. Your file's SHA-256 matches its line in that manifest.

**Step 2 is worthless without step 1.** Anyone who alters an artefact can
recompute its checksum and rewrite the manifest; what they cannot do is
re-sign it. Never check a digest against a manifest whose signature you have
not verified.

The Windows and macOS binaries may also carry a platform code signature
(Authenticode, and Apple notarization), which your operating system checks by
itself. The signature here is independent of that and can be verified on any
platform.

**Quick verify:**

```bash
# One artefact
bash scripts/verify_release.sh EDLD-20261009-linux-x86_64.tar.gz

# Or every artefact you downloaded, from the download directory
bash scripts/verify_release.sh
```

The script finds `allowed_signers` beside your downloads or in the checkout it
came from, refuses any key in it whose fingerprint it does not already know,
then checks the signature and the digests.

**Manual verify:**

```bash
# 1. Authenticate the manifest — this must pass before the checksums mean
#    anything at all
ssh-keygen -Y verify \
    -f signing/allowed_signers \
    -I indevlin-vcs@indevlin.com \
    -n edld.release \
    -s EDLD-20261009.sha256.sig \
    < EDLD-20261009.sha256

# 2. Check your download against the now-trusted manifest.
#    --ignore-missing checks only the files you actually downloaded.
sha256sum -c --ignore-missing EDLD-20261009.sha256
```

---

## The release key

The key that signs new releases is committed at
`signing/id_ed25519_signing.pub`, and every key that has signed a release
still on the releases page is listed in `signing/allowed_signers`. Their
fingerprints:

```
SHA256:fQaV3r44Ilmjd2RXNN70SDuDcfh/NjKZ7EQHS6p4YKo  indevlin-vcs@indevlin.com (ED25519)  current
SHA256:cLyptjOnhuQWARi4TGvLp1Gr3VCqx6MFE+KtWEY5KXI  indevlin-edld-release (ED25519)  retired
```

Check before trusting: `ssh-keygen -lf signing/id_ed25519_signing.pub` must
print the current one. A key file can be replaced as easily as a checksum
list, so compare against something you did not download alongside it — this
page on the primary server, git.indevlin.com. `scripts/verify_release.sh`
carries the same list and checks it for you.

`indevlin-vcs@indevlin.com` is a label, not an address anything is sent to or
checked against. An SSH signature records a key and a namespace and nothing
about a person, which is also why relabelling a key — as happened when EDLD
moved to the `indevlin` organization — leaves every signature it made
valid.

---

## Signed commits and tags

Commits and tags are SSH-signed by the maintainer who made them, with a key
registered as a signing key on that maintainer's GitHub account, which is what
puts a **Verified** badge on them. Git finds the signing key in your
`allowed_signers` and reports the principal listed with it; by convention that
is the committer's email, which `git log` supplies:

```bash
# One-time setup, from a clone
echo "$(git log -1 --format=%ce) namespaces=\"git\" $(cut -d' ' -f1,2 signing/id_ed25519_signing.pub)" \
    >> ~/.ssh/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers

git log --show-signature -1       # a commit
git tag -v 20260926               # a tag
```

That authenticates the source through git's own object hashing, which is a
stronger guarantee than a digest in a manifest: it covers the full history, not
one snapshot.

Today the release key is also the maintainer's commit key, which is why the
line above reads it from `signing/`. If the two are ever separated (see
*Rotating the release key*), use the maintainer's published commit key there
instead.

---

## Release flow

EDLD uses `git.indevlin.com` (`idev`) as the authoritative source and
`github.com/indevlin/EDLD` (`ghub`) as its mirror.

```
1. Finish work on dev, merge to main
2. git checkout main
3. git tag -s 20261009 -m 'Release 20261009'   # signed tag, matching ./version
4. gpublish                                     # push to idev, mirror to ghub
```

Pushing the tag starts the Release workflow. It checks the tag matches the
`version` file, builds and smoke-tests the five binaries, writes the checksum
manifest, checks that the `SIGNING_KEY` secret is the key in
`signing/id_ed25519_signing.pub`, signs the manifest, and verifies it exactly
as a user does — against `signing/allowed_signers`, then every digest — before
publishing the release with notes from `CHANGELOG.md`. It also asserts the
manifest covers five artefacts, so a glob that quietly matched fewer fails the
build rather than shipping a release that verifies while missing a platform.

Publishing a release by hand in the GitHub UI runs the same workflow, and a
manual run from the Actions tab builds any branch without publishing
(`dry_run`). See the comments at the top of `.github/workflows/release.yml`.

---

## Maintainer setup

One repository secret signs releases (Settings → Secrets and variables →
Actions, on `indevlin/EDLD`):

| Secret | Content |
|---|---|
| `SIGNING_KEY` | The release private key: ed25519, no passphrase, whose public half is `signing/id_ed25519_signing.pub` |

The signing identity is not a secret; it is `indevlin-vcs@indevlin.com`, set in
the workflow and in `signing/allowed_signers`. The `SIGNING_IDENTITY` secret
older workflows read is not used by this one. A run uses the workflow file in
the commit it builds, so keep that secret until `main` and `dev` both carry
this workflow, then delete it.

### Rotating the release key

Not required on a schedule. Do it if the key may have been exposed, or to give
releases a key of their own, separate from the maintainer's commit key.

```bash
# 1. A new key, on a trusted machine; the private half never enters the repo
ssh-keygen -t ed25519 -N "" -C indevlin-edld-release -f ~/indevlin-edld-release

# 2. The repository: the new public key, and the new key added to the list
cp ~/indevlin-edld-release.pub signing/id_ed25519_signing.pub
echo "indevlin-vcs@indevlin.com namespaces=\"edld.release\" $(cat ~/indevlin-edld-release.pub)" \
    >> signing/allowed_signers
ssh-keygen -lf ~/indevlin-edld-release.pub      # the new fingerprint
```

3. Add that fingerprint to `RELEASE_KEY_FPS` in `scripts/verify_release.sh`
   and to the list above, marking the old one *retired*.
4. Replace the `SIGNING_KEY` secret with the new private key, then delete the
   local private copy or move it offline.
5. Commit, and tag the next release.

Leave a retired key in `allowed_signers` and `RELEASE_KEY_FPS` for as long as
releases it signed are on the releases page; removing it only makes those
releases unverifiable.
