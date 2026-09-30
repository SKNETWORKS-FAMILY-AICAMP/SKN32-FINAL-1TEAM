import assert from 'node:assert/strict';
import {createServer} from 'vite';

const cache = new Map();
globalThis.localStorage = {
  getItem: key => cache.get(key) ?? null,
  setItem: (key, value) => cache.set(key, value),
  removeItem: key => cache.delete(key),
};
globalThis.window = {localStorage: globalThis.localStorage};
const originalFetch = globalThis.fetch;
const server = await createServer({configFile:false, resolve:{preserveSymlinks:true}, server:{middlewareMode:true}, appType:'custom'});
const response = (data, status = 200) => ({ok:status < 400, status, text:async () => JSON.stringify(data)});
const deferredRequest = () => {
  let complete;
  globalThis.fetch = () => new Promise(resolve => { complete = data => resolve(response(data)); });
  return data => complete(data);
};
try {
  const {useMyPageStore: store} = await server.ssrLoadModule('/src/store/useMyPageStore.js');
  const seed = () => {
    store.getState().reset();
    store.getState().renameProfile(0, 'A');
    store.getState().addProfile('B');
    store.getState().addProfile('C');
    store.getState().selectProfile(1);
  };
  seed();
  let complete = deferredRequest();
  let pending = store.getState().saveActiveProfile();
  await store.getState().removeProfile(0);
  complete({profile_id:2, name:'B', basic:{}, capability:{}});
  await pending;
  assert.deepEqual(store.getState().profiles.map(p => p.name), ['B','C']);
  assert.equal(store.getState().profiles[0].profileId, 2);
  assert.equal(store.getState().activeIndex, 0);

  seed();
  complete = deferredRequest();
  pending = store.getState().saveActiveProfile();
  store.getState().patch('basic', {ceoName:'edited during save'});
  complete({profile_id:2, name:'B', basic:{ceoName:'old'}, capability:{}});
  await pending;
  assert.equal(store.getState().profiles[1].basic.ceoName, 'edited during save');

  for (const action of ['loadProfiles', 'saveActiveProfile']) {
    seed();
    complete = deferredRequest();
    pending = store.getState()[action]();
    store.getState().reset();
    const old = {profile_id:2, name:'PREVIOUS_USER', basic:{}, capability:{}};
    complete(action === 'loadProfiles' ? [old] : old);
    await pending;
    assert.equal(store.getState().profiles[0].name, '정보 1');
    assert.equal(store.getState().onboarded, false);
  }

  seed();
  store.getState().patch('basic', {bizNo:'123-45-67890'});
  const target = store.getState().profiles[1];
  const generation = store.getState().generation;
  store.getState().selectProfile(2);
  store.getState().setBizStatus(target.localId, generation, {checkedNo:'123-45-67890',valid:true});
  assert.equal(store.getState().profiles[1].bizStatus.valid, true);
  assert.equal(store.getState().profiles[2].bizStatus, null);
  store.getState().selectProfile(1);
  store.getState().patch('basic', {bizNo:'999-99-99999'});
  store.getState().setBizStatus(target.localId, generation, {checkedNo:'123-45-67890',valid:false});
  assert.equal(store.getState().profiles[1].bizStatus.valid, true);

  const {fetchCurrentUser} = await server.ssrLoadModule('/src/components/Login.jsx');
  const calls = [];
  globalThis.fetch = async url => {
    calls.push(String(url));
    return response(calls.length === 3 ? {user_id:7} : {}, calls.length === 1 ? 401 : 200);
  };
  assert.equal((await fetchCurrentUser()).user_id, 7);
  assert.deepEqual(calls.map(url => new URL(url).pathname), ['/auth/me','/auth/refresh','/auth/me']);
  console.log('PASS: profile identity, edits during save, logout races, business lookup target, login refresh');
} finally {
  globalThis.fetch = originalFetch;
  await server.close();
}
