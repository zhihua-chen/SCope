import React, { Component } from 'react';
import { withRouter, Link } from 'react-router-dom';
import { Segment,  Sidebar, Menu, Icon, Image, Divider,  Checkbox, Dropdown, Grid, Dimmer, Loader } from 'semantic-ui-react';
import { BackendAPI } from './common/API';
import UploadModal from './common/UploadModal';
import Slider, { Range } from 'rc-slider';
import ReactGA from 'react-ga';

const createSliderWithTooltip = Slider.createSliderWithTooltip;
const TooltipSlider = createSliderWithTooltip(Slider);

class AppSidebar extends Component {

	constructor() {
		super();
		let sprite = BackendAPI.getSpriteSettings();
		this.state = {
			activeCoordinates: BackendAPI.getActiveCoordinates(),
			settings: BackendAPI.getSettings(),
			loomFiles: [],
			userLoomFiles: [],
			generalLoomFiles: [], 
			spriteScale: sprite.scale,
			spriteAlpha: sprite.alpha,
			uploadModalOpened: false,
			loading: true
		}
	}

	render () {
		const { match } = this.props;
		const { activeCoordinates, settings, loading, loomFiles, userLoomFiles, generalLoomFiles, uncategorizedLoomFiles, uploadModalOpened, spriteScale, spriteAlpha } = this.state;
		let metadata = {}, coordinates = [];
		loomFiles.map(loomFile => {
			if (loomFile.loomFilePath == decodeURIComponent(match.params.loom)) {
				metadata = loomFile;
				coordinates = metadata.cellMetaData.embeddings.map(coords => {
					return {
						text: coords.name,
						value: coords.id
					}
				})
			}
		})
		let showTransforms = metadata && (['welcome', 'dataset', 'tutorial', 'about'].indexOf(match.params.page) == -1) ? true : false;
		let showCoordinatesSelection = showTransforms && metadata.fileMetaData && metadata.fileMetaData.hasExtraEmbeddings ? true : false;
		let renderLoomFiles = (files) => {
			let tree = {
				nodes: [],
				children: {},
			}
			let addChildren = (t, l, f) => {
				if (f.loomHeierarchy['L'+l]) {
					t.children[f.loomHeierarchy['L'+l]] = t.children[f.loomHeierarchy['L'+l]] || {nodes: [], children: {}}
					addChildren(t.children[f.loomHeierarchy['L'+l]], l+1, f);
				} else {
					t.nodes.push(f);
				}
			}
			files.forEach((file, i) => {
				addChildren(tree, 1, file);
			});
			let renderLevel = (t, l) => {
				let nodes = t.nodes.map((file, i) => {
					let loomUri = encodeURIComponent(file.loomFilePath);
					let active = (match.params.loom == loomUri) || (encodeURIComponent(match.params.loom) == loomUri);
					return (
						<Link key={i} to={'/' + [match.params.uuid, loomUri, match.params.page == 'welcome' ? 'gene' : match.params.page ].join('/')} onClick={() => {
							this.props.onMetadataChange(file);
						}}  >
							<Menu.Item className={'level'+l} active={active} key={file.loomFilePath} >
								<Icon name={active ? "selected radio" : "radio"} />
								{file.loomDisplayName}
							</Menu.Item>
						</Link>
					)
				})
				let children = Object.keys(t.children).map((level) => {
					return (
						<div>
							<Menu.Header className={'level'+l}>{level}</Menu.Header>
							{renderLevel(t.children[level], l+1)}
						</div>
					)
				}) 
				return (
					<div>
						{nodes}
						{children}
					</div>
				);
			}
			return renderLevel(tree, 1);
		}

		return (
			<Sidebar as={Menu} animation="push" visible={this.props.visible} vertical className="clearfix">
					<Segment basic>
						<Icon name='arrow up' /><em>Hide me to get bigger workspace</em>
					</Segment>
					<Menu.Header>DATASETS</Menu.Header>
						<Menu.Menu>
							<Menu.Header className="level0">User uploaded</Menu.Header>
							<Menu.Item key="new" onClick={this.toggleUploadModal.bind(this)}>
								<Icon name="add" />
								<em>Upload new dataset</em>
							</Menu.Item>
							{renderLoomFiles(userLoomFiles)}
							{generalLoomFiles.length ? <Menu.Header className="level0">Publicly available</Menu.Header> : '' }
							{renderLoomFiles(generalLoomFiles)}
							<Dimmer active={loading} inverted>
								<Loader inverted>Loading</Loader>
							</Dimmer>
						</Menu.Menu>
					<Divider />
					{(showTransforms || showCoordinatesSelection) &&
						<Menu.Header>SETTINGS</Menu.Header>
					}
						
					{showCoordinatesSelection &&
						<Menu.Menu>
							<Menu.Item>Coordinates</Menu.Item>
							<Menu.Item>
								<Dropdown inline defaultValue={activeCoordinates} options={coordinates} onChange={this.setActiveCoordinates.bind(this)} />
							</Menu.Item>
						</Menu.Menu>
					}
					{ showTransforms && 
						<Menu.Menu>
							<Menu.Item>Gene expression</Menu.Item>
							<Menu.Item>
								<Checkbox toggle label="Log transform" checked={settings.hasLogTransform} onChange={this.toggleLogTransform.bind(this)} />
							</Menu.Item>
							<Menu.Item>
								<Checkbox toggle label="CPM normalize" checked={settings.hasCpmNormalization} onChange={this.toggleCpmNormization.bind(this)} />
							</Menu.Item>
							<Menu.Item>Plot enhancement</Menu.Item>
							<Menu.Item>
								<Checkbox toggle label="Expression-based plotting" checked={settings.sortCells} onChange={this.toggleSortCells.bind(this)} />
							</Menu.Item>
							<Menu.Item>Point size</Menu.Item>
							<Menu.Item>
								<TooltipSlider
								style={{margin: '5px'}} 
								max={20}
								defaultValue={spriteScale}
								onAfterChange={(v) => {
									this.handleUpdateSprite(v, spriteAlpha);
									ReactGA.event({
										category: 'settings',
										action: 'changed point size',
										value: v
									});
								}}
								min={1}
								step={1}
								tipFormatter={(v) => {
									return v.toFixed(1);
								}}
							/>
							</Menu.Item>
							<Menu.Item>Point alpha</Menu.Item>
							<Menu.Item>
								<TooltipSlider
								style={{margin: '5px'}} 
								max={1}
								defaultValue={spriteAlpha}
								onAfterChange={(v) => {
									this.handleUpdateSprite(spriteScale, v);
									ReactGA.event({
										category: 'settings',
										action: 'changed point alpha',
										value: v
									});
								}}
								min={0}
								step={0.1}
								tipFormatter={(v) => {
									return v.toFixed(1);
								}}
							/>
							</Menu.Item>
						</Menu.Menu>
					}
					<Divider />
					<Menu.Menu className="logos">
						{/*<Image src='src/images/kuleuven.png' size="small" centered href="http://kuleuven.be" />
						<br /><br />
						<Image src='src/images/vib.png' size="small" centered href="http://vib.be" />
						<Image src='src/images/flycellatlas.png' size="small" centered href="http://flycellatlas.org/" />*/}
					</Menu.Menu>
				<UploadModal title="Import a .loom file" type='Loom' uuid={match.params.uuid} opened={uploadModalOpened} onClose={this.toggleUploadModal.bind(this)} onUploaded={this.onLoomUploaded.bind(this)} />
			</Sidebar>
		);
	}

	componentWillMount() {
		this.getLoomFiles();
	}

	getLoomFiles(loom, page) {
		const { match } = this.props;
		let { generalLoomFiles, userLoomFiles, uncategorizedLoomFiles } = this.state;
		BackendAPI.queryLoomFiles(match.params.uuid, (files) => {
			files.map((file) => {
				if (file.loomFilePath.indexOf('\\') != -1) {
					userLoomFiles.push(file);
				} else {
					generalLoomFiles.push(file);
				}
			});
			this.setState({ loomFiles: files, loading: false });
			this.props.onMetadataChange(BackendAPI.getActiveLoomMetadata());
		});
	}

	toggleUploadModal(event) {
		let state = !this.state.uploadModalOpened;
		this.setState({ uploadModalOpened: state })
		ReactGA.event({
			category: 'upload',
			action: 'toggle loom upload modal',
			label: state ? 'on' : 'off'
		});
	}

	toggleSortCells() {	
		let settings = BackendAPI.setSetting('sortCells', !this.state.settings.sortCells);
		this.setState({settings: settings});
		ReactGA.event({
			category: 'settings',
			action: 'toggle cell sorting',
			label: settings.sortCells ? 'on' : 'off'
		});
	}

	toggleCpmNormization() {	
		let settings = BackendAPI.setSetting('hasCpmNormalization', !this.state.settings.hasCpmNormalization);
		this.setState({settings: settings});
		ReactGA.event({
			category: 'settings',
			action: 'toggle cpm normalization',
			label: settings.hasCpmNormalization ? 'on' : 'off'
		});
	}

	toggleLogTransform() {
		let settings = BackendAPI.setSetting('hasLogTransform', !this.state.settings.hasLogTransform);
		this.setState({settings: settings});
		ReactGA.event({
			category: 'settings',
			action: 'toggle log transform',
			label: settings.hasCpmNormalization ? 'on' : 'off'
		});
	}

	setActiveCoordinates(evt, coords) {
		BackendAPI.setActiveCoordinates(coords.value);
		this.setState({ activeCoordinates: coords.value });
		ReactGA.event({
			category: 'settings',
			action: 'changed active coordinates',
			label: coords.text
		});
	}

	onLoomUploaded(filename) {
		this.getLoomFiles(filename, 'gene');
		this.toggleUploadModal();
		ReactGA.event({
			category: 'upload',
			action: 'uploaded loom file',
			nonInteraction: true
		});
	}

	handleUpdateSprite(scale, alpha) {
		this.setState({spriteScale: scale, spriteAlpha: alpha})
		BackendAPI.setSpriteSettings(scale, alpha);
	}
}

export default withRouter(AppSidebar);