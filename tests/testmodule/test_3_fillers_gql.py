
import repo_tools
from repo_tools.fillers import generic,commit_info,github_gql,meta_fillers,github_rest,snowball
import pytest
import datetime
import time
import os
import subprocess

#### Parameters
dbtype_list = [
	'sqlite',
	'postgres'
	]
@pytest.fixture(params=dbtype_list)
def dbtype(request):
	return request.param


@pytest.fixture(params=dbtype_list)
def testdb(request):
	db = repo_tools.repo_database.Database(db_name='travis_ci_test_repo_tools',db_type=request.param,data_folder='dummy_clones')
	db.clean_db()
	db.init_db()
	yield db
	db.connection.close()
	del db

workers = 3

##############

#### Tests

@pytest.mark.timeout(300)
def test_github_gql(testdb):
	testdb.add_filler(generic.SourcesFiller(source=['GitHub',],source_urlroot=['github.com',]))
	testdb.add_filler(generic.PackageFiller(package_list_file='packages.csv',data_folder=os.path.join(os.path.dirname(__file__),'dummy_data')))
	testdb.add_filler(generic.RepositoriesFiller())
	# testdb.add_filler(github_rest.ForksFiller(fail_on_wait=True,workers=workers,no_unauth=True))
	testdb.add_filler(github_gql.ForksGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(generic.ClonesFiller(data_folder='dummy_clones')) # Clones after forks to have up-to-date repo URLS (detect redirects)
	testdb.add_filler(commit_info.CommitsFiller(data_folder='dummy_clones',force=True,allbranches=True)) # Commits after forks because fork info needed for repo commit ownership
	# testdb.add_filler(github_gql.LoginsGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.RandomCommitLoginsGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.StarsGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.ReleasesGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.FollowersGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.LanguagesGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.SponsorsUserFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.IssuesGQLFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(github_gql.BackwardsSponsorsUserFiller(fail_on_wait=True,workers=workers))
	testdb.add_filler(generic.RepoCommitOwnershipFiller()) # Clones after forks to have up-to-date repo URLS (detect redirects)
	testdb.add_filler(snowball.UserSnowballFiller())

	testdb.fill_db()