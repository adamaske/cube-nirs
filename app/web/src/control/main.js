import { mount } from 'svelte';
import App from './App.svelte';
import { connect } from '../lib/ws.js';

connect();
export default mount(App, { target: document.getElementById('app') });
