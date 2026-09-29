# COPR builds the source package with
# make -f .copr/Makefile srpm outdir=<dir> spec=<file>
spec ?= wisp-helper.spec
outdir ?= $(CURDIR)
version = $(shell sed -n 's/^Version:[[:space:]]*//p' $(spec))

# As root, git refuses a clone that belongs to another user.
srpm:
	rpm -q git rpm-build >/dev/null || dnf -y install git rpm-build
	git -c safe.directory='*' archive --prefix=wisp-helper-$(version)/ -o $(outdir)/wisp-helper-$(version).tar.gz HEAD
	rpmbuild -bs $(spec) --define '_sourcedir $(outdir)' --define '_srcrpmdir $(outdir)'
