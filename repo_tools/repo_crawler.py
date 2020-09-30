import subprocess
import os
import shutil
import copy
import pygit2
import logging
import numpy as np
import datetime

from .repo_database import Database

logger = logging.getLogger(__name__)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)
logger.setLevel(logging.INFO)

class RepoSyntaxError(ValueError):
	'''
	raised when syntax error is encountered in repository url
	'''
	pass


class RepoCrawler(object):
	'''
	This class implements a crawler of repositories from github.

	Mode SSH vs HTTPS
	Even non existing repositories trigger an authentication request, which waits for input

	A folder can be specified as root (default '.'), where the DB lies, and repos are cloned in its subfolder: PATH/cloned_repos

	'''
	def __init__(self,folder='.',ssh_mode=False,ssh_key=os.path.join(os.environ['HOME'],'.ssh/id_rsa'),db_folder=None,**db_cfg):
		# self.repo_list = []
		# self.add_list(repo_list)
		self.folder = folder
		self.make_folder() # creating folder if not existing
		self.logger = logger
		self.ssh_mode = ssh_mode #SSH if True, HTTPS otherwise
		if ssh_mode: # setting ssh credentials
			keypair = pygit2.Keypair('git',ssh_key+'.pub',ssh_key,'')
			self.callbacks = pygit2.RemoteCallbacks(credentials=keypair)
		else:
			self.callbacks = None

		if db_folder is None:
			db_folder = self.folder
		self.set_db(db_folder=db_folder,**db_cfg)

	def add_list(self,repo_list,source,source_urlroot):
		'''
		Behaving like an ordered set, if performance becomes an issue it could be useful to use OrderedSet implementation
		Or simply code an option to disable checks
		'''
		repo_list = copy.deepcopy(repo_list) #deepcopy to avoid unwanted modif of default arg

		self.db.register_source(source=source,source_urlroot=source_urlroot)

		for r in repo_list:
			self.db.register_url(repo_url=r,source=source)
			try:
				r_f = self.repo_formatting(r,source_urlroot)
			except RepoSyntaxError:
				pass
			else:
				owner,repo = r_f.split('/')
				self.db.register_repo(repo=repo,owner=owner,source=source)
				repo_id = self.db.get_repo_id(name=repo,owner=owner,source=source)
				self.db.update_url(source=source,repo_url=r,repo_id=repo_id)

		# 	if r_f not in self.repo_list:
		# 		self.repo_list.append(r_f)

	# def set_db(self,db=None,db_folder=None,db_name='',db_user='postgres',db_host='localhost',db_type='sqlite',db_port=5432):
	def set_db(self,db=None,**db_cfg):
		'''
		Sets up the database
		'''

		if db is not None:
			self.db = db
		else:
			self.db = Database(**db_cfg)



	def repo_formatting(self,repo,source_urlroot):
		'''
		Formatting repositories so that they match the expected syntax 'user/project'
		'''
		r = copy.copy(repo)
		for start_str in [
					'https://{}/'.format(source_urlroot),
					'http://{}/'.format(source_urlroot),
					'https://www.{}/'.format(source_urlroot),
					'http://www.{}/'.format(source_urlroot),
					]:
			if r.startswith(start_str):
				r = '/'.join(r.split('/')[3:])
		if r.endswith('/'):
			r = r[:-1]
		if r.endswith('.git'):
			r = r[:-4]
		if len(r.split('/')) != 2:
			raise RepoSyntaxError('Repo has not expected syntax "user/project" or prefixed with {}:{}. Please fix input or update the repo_formatting method.'.format(source_urlroot,repo))
		r = '/'.join(r.split('/')[:2])
		return r

	def list_missing_repos(self):
		'''
		List of repos that are in the repo_list but do not have a local cloned folder
		'''
		ans = []
		for r in self.repo_list:
			if not os.path.exists(os.path.join(self.folder,'cloned_repos',r)):
				ans.append(r)
		return ans


	def add_list_from_file(self,filepath,limit=-1):
		with open(filepath,'r') as f:
			repos = f.read().split('\n')
		if limit is not None:
			self.add_list(repos[:limit])
		else:
			self.add_list(repos)



	def build_url(self,name,owner,source_urlroot):
		'''
		building url, depending on mode (ssh or https)
		'''
		if self.ssh_mode:
			return 'git@{}:{}/{}'.format(source_urlroot,owner,name)
		else:
			return 'https://{}/{}/{}.git'.format(source_urlroot,owner,name)

	def make_folder(self):
		'''
		creating folder if not existing
		'''
		if not os.path.exists(self.folder):
			os.makedirs(self.folder)
		if not os.path.exists(os.path.join(self.folder,'cloned_repos')):
			os.makedirs(os.path.join(self.folder,'cloned_repos'))

	def clone_all(self,force=False,update=False):
		repo_list = self.db.get_repo_list()
		for i,r in enumerate(repo_list):
			source,source_urlroot,owner,name = r
			self.logger.info('Repo {}/{}'.format(i+1,len(repo_list)))
			self.clone(source=source,name=name,owner=owner,source_urlroot=source_urlroot,force=force,update=update)

	def clone(self,source,name,owner,source_urlroot,force=False,replace=False,update=False):
		'''
		Cloning one repo.
		Skipping if folder exists by default; not if force=True, in this case delete folder and restart
		Executing update_repo if repo already exists and update is True

		Returns the status of the cloning process
		'''
		repo_folder = os.path.join(self.folder,'cloned_repos',source,owner,name)
		if os.path.exists(repo_folder):
			if replace:
				self.logger.info('Removing folder {}/{}/{}'.format(source,owner,name))
				shutil.rmtree(repo_folder)
				self.clone(source=source,name=name,owner=owner,source_urlroot=source_urlroot)
			elif update:
				self.update_repo(source=source,name=name,owner=owner,source_urlroot=source_urlroot)
			else:
				self.logger.info('Repo {}/{}/{} already exists'.format(source,owner,name))
				repo_id = self.db.get_repo_id(source=source,name=name,owner=owner)
				if self.db.get_last_dl(repo_id=repo_id,success=True) is None:
					repo_obj = self.get_repo(source=source,owner=owner,name=name)
					last_commit_time = datetime.datetime.fromtimestamp(repo_obj.revparse_single('HEAD').commit_time)
					self.db.submit_download_attempt(source=source,owner=owner,repo=name,success=True,dl_time=last_commit_time)
		else:
			repo_id = self.db.get_repo_id(source=source,name=name,owner=owner)
			if self.db.db_type == 'postgres':
				self.db.cursor.execute('SELECT * FROM download_attempts WHERE repo_id=%s LIMIT 1;',(repo_id,))
			else:
				self.db.cursor.execute('SELECT * FROM download_attempts WHERE repo_id=? LIMIT 1;',(repo_id,))

			if (self.db.cursor.fetchone() is None) or force:
				self.logger.info('Cloning repo {}/{}/{}'.format(source,owner,name))
				try:
					pygit2.clone_repository(url=self.build_url(source_urlroot=source_urlroot,name=name,owner=owner),path=repo_folder,callbacks=self.callbacks)
					success = True
				except pygit2.GitError as e:
					self.logger.info('Git Error for repo {}/{}/{}'.format(source,owner,name))
					success = False
				self.db.submit_download_attempt(success=success,source=source,repo=name,owner=owner)
			else:
				self.logger.info('Skipping repo {}/{}/{}, already failed to download'.format(source,owner,name))

	def update_repo(self,name,source,source_urlroot,owner):
		'''
		git fetch on repo
		cloning if folder not existing
		'''
		self.logger.info('Updating repo {}/{}/{}'.format(source,owner,name))
		repo_folder = os.path.join(self.folder,'cloned_repos',source,owner,name)

		repo_obj = pygit2.Repository(os.path.join(repo_folder,'.git'))
		try:
			repo_obj.remotes["origin"].fetch(callbacks=self.callbacks)
			success = True
		except pygit2.GitError as e:
			self.logger.info('Git Error for repo {}/{}/{}'.format(source,owner,name))
			success = False

		self.db.submit_download_attempt(success=success,source=source,repo=name,owner=owner)

	def get_repo(self,name,source,owner):
		'''
		Returns the pygit2 repository object
		'''
		repo_folder = os.path.join(self.folder,'cloned_repos',source,owner,name)
		if not os.path.exists(repo_folder):
			raise ValueError('Repository {}/{}/{} not found in cloned_repos folder'.format(source,owner,name))
		else:
			return pygit2.Repository(os.path.join(repo_folder,'.git'))


	def list_commits(self,name,source,owner,basic_info_only=False,repo_id=None):
		'''
		Listing the commits of a repository
		'''
		repo_obj = self.get_repo(source=source,name=name,owner=owner)
		if repo_id is None: # Letting the possibility to preset repo_id to avoid cursor recursive usage
			repo_id = self.db.get_repo_id(source=source,name=name,owner=owner)
		# repo_obj.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE)
		for commit in repo_obj.walk(repo_obj.head.target, pygit2.GIT_SORT_TIME | pygit2.GIT_SORT_REVERSE):
			if basic_info_only:
				yield {
						'author_email':commit.author.email,
						'author_name':commit.author.name,
						'time':commit.commit_time,
						'time_offset':commit.commit_time_offset,
						'sha':commit.hex,
						'parents':[pid.hex for pid in commit.parent_ids],
						'repo_id':repo_id,
						}
			else:
				if commit.parents:
					diff_obj = repo_obj.diff(commit.parents[0],commit)# Inverted order wrt the expected one, to have expected values for insertions and deletions
					insertions = diff_obj.stats.insertions
					deletions = diff_obj.stats.deletions
				else:
					diff_obj = commit.tree.diff_to_tree()
					# re-inverting insertions and deletions, to get expected values
					deletions = diff_obj.stats.insertions
					insertions = diff_obj.stats.deletions
				yield {
						'author_email':commit.author.email,
						'author_name':commit.author.name,
						'time':commit.commit_time,
						'time_offset':commit.commit_time_offset,
						'sha':commit.hex,
						'parents':[pid.hex for pid in commit.parent_ids],
						'insertions':insertions,
						'deletions':deletions,
						'total':insertions+deletions,
						'repo_id':repo_id,
						}


	def fill_commit_info(self,force=False):
		'''
		Filling in authors, commits and parenthood using Database object methods
		'''

		self.db.cursor.execute('''SELECT MAX(updated_at) FROM full_updates WHERE update_type='commits';''')
		last_fu = self.db.cursor.fetchone()[0]

		self.db.cursor.execute('SELECT MAX(attempted_at) FROM download_attempts WHERE success;')
		last_dl = self.db.cursor.fetchone()[0]
		
		print(last_fu,last_dl)

		if force or (last_fu is None) or (last_fu<last_dl): 
			
			self.logger.info('Filling in users')

			for repo_info in self.db.get_repo_list(option='basicinfo_dict'):
				self.db.fill_authors(self.list_commits(basic_info_only=True,**repo_info))
			self.db.create_indexes(table='users')
			
			self.logger.info('Filling in commits')

			for repo_info in self.db.get_repo_list(option='basicinfo_dict'):
				self.db.fill_commits(self.list_commits(basic_info_only=False,**repo_info))
			self.db.create_indexes(table='commits')

			self.logger.info('Filling in commit parents')
	
			for repo_info in self.db.get_repo_list(option='basicinfo_dict'):
				self.db.fill_commit_parents(self.list_commits(basic_info_only=True,**repo_info))
			self.db.create_indexes(table='commit_parents')

			self.db.cursor.execute('''INSERT INTO full_updates(update_type,updated_at) VALUES('commits',(SELECT CURRENT_TIMESTAMP));''')
			self.db.connection.commit()
		else:
			self.logger.info('Skipping filling of commits info')

	def fill_stars(self,force=False):
		'''
		Filling stars (only from github for the moment)
		'''
		# create tables
		# check full updates
		# query github through pygithub / or through curl
		pass