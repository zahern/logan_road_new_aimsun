	subroutine PrintLinkProportions(starttime,endtime,outputtype)

	use muc_mod 
	use vector_mod

	integer(4) starttime,endtime
	integer outputtype,iDestination,iDemandInterval
	integer i,value1,value2,inonzeronum,iOrigin,error
	integer iObservationTimeInterval,iObservationInterval
	integer nint_obs,nint_demand
c	 Number of observation intervals, Number of demand intervals
	real LinkEnterTime,LinkExitTime,LinkProportion
	character *20 ErString

	integer(2),allocatable::LinkIndex_obs(:)
	real,allocatable::LP_ODDemand(:,:,:)
c	 ODDemand: the demand for dest j and OD interval t, link k, observation time interval t
	real,allocatable::LP_ODFlow(:,:,:,:,:)
c	 ODFlow: the demand for dest j and OD interval t, link k, observation time interval t
	iObservationTimeInterval=1
	iDemandTimeInterval=5
	inonzeronum=0
c	Read link Index with observation
	allocate(LinkIndex_obs(noofarcs_org),stat=error)
	if(error.ne.0)then
	  write(911,*) 'allcoate LinkIndex_obs error-insufficient memory'
	  stop
	endif
	LinkIndex_obs(:)=1
c	By default, we output complete link observations
	if(outputtype.eq.0)then
	write(*,*) "Processing link flow proportions"

	open(file='LinkProp.inc',unit=901,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening LinkFlowProportions.dat'
	   stop
	endif
	endif

	if(outputtype .eq.1) then
	write(*,*) "Processing link density proportions"

	open(file='LinkProp.inc',unit=901,status='unknown',iostat=error)
	if(error.ne.0) then
         write(911,*) 'Error when opening LinkDensityProportions.dat'
	   stop
	endif
	endif

	open(file='linkwithobs.dat',unit=914,status='old',iostat=error) 
	if(error.ne.0) then
!         write(911,*) 'Error when opening linkwithobs.dat'
	else

	! read linkwithobs.dat based on the 
	!  the original number of links
	do i=1,noofarcs_org
		  read(914,*) LinkIndex_obs(i)
	enddo
		  close(914)

	endif

	if(outputtype .eq.0) then
	write(901,*) "PARAMETER LINKP(I,J,D.K,T) /"
	endif

	if(outputtype .eq.1) then
	write(901,*) "PARAMETER LINKP(I,J,D.K,T) /"
	endif

	nint_demand = (endtime- starttime)/10/iDemandTimeInterval

	allocate (LP_ODDemand(nzones,nzones,nint_demand),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate LP_ODDemand error - insufficient memory'
	  stop
	endif

	nint_obs = endtime/(iObservationTimeInterval/tii) +1

	allocate(LP_ODFlow(nzones,nzones,nint_demand,noofarcs_org,
     +  nint_obs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate LP_ODFlow error-insufficient memory'
	  stop
	endif
		LP_ODDemand(:,:,:)=0
		LP_ODFlow(:,:,:,:,:)=0
 	do j=1, jj
   	iVehicleorigin=izone(iunod(isec(j)))
        iDestination=jdest(j)
        sttime=stime(j)
       if(iOrigin.ne.iDestination)then  ! do not count the intrazone demand
	iDemandInterval=nint(sttime/iDemandTimeInterval)+1
	if(iDemandInterval.ge.nint_demand)then
		iDemandInterval=nint_demand
	endif
	LP_ODDemand(iVehicleorigin,iDestination,iDemandInterval) 
     +  =LP_ODDemand(iVehicleorigin,iDestination,iDemandInterval)+1
	   endif
	   iVhcAttsize=VhcAtt_Size(j)-2
	   if(notin(j)==0)then ! incomplete vehicle
		   iVhcAttsize=VhcAtt_Size(j)-2
       endif	   
	   do jn=1,iVhcAttsize
		   iUpstreamNode = VhcAtt_Value(j,jn,1)
		   iDownstreamNode = VhcAtt_Value(j,jn+1,1)
	iLinkNo = GetOriginFLinkFromNode(iUpstreamNode,iDownstreamNode)
		   LinkEnterTime = VhcAtt_Value(j,jn,3)			
		   LinkExitTime = VhcAtt_Value(j,jn+1,3)			

c	output link flow proportions
		   if(outputtype .eq. 0) then
	iObservationInterval=int((sttime+(LinkEnterTime+LinkExitTime)/2)
     +  /iObservationTimeInterval) +1 
			   if(iLinkNo .NE. 0 ) then
	LP_ODFlow(iVehicleorigin,iDestination,iDemandInterval,iLinkNo,
     +  iObservationInterval) = LP_ODFlow(iVehicleorigin,iDestination, 
     +  iDemandInterval,iLinkNo, iObservationInterval) +1
			   endif
		   endif
c 	output link density proportions
		   if(outputtype.eq.1)then
		      iStartObsInterval=
     + (sttime+LinkEnterTime)/iObservationTimeInterval+1
	iEndObsInterval=(sttime+LinkExitTime)/iObservationTimeInterval
		do iObservationInterval=iStartObsInterval,iEndObsInterval
			   if(iLinkNo.NE.0)then
	LP_ODFlow(iVehicleorigin,iDestination,iDemandInterval,iLinkNo,
     +  iObservationInterval)=LP_ODFlow(iVehicleorigin,iDestination, 
     +  iDemandInterval,iLinkNo,iObservationInterval)+1
			   endif
		enddo
		   endif
	   enddo
 	enddo
c 	count non-zero elements
	do iOrigin = 1, nzones
 	do  iDestination = 2, nzones
    	do iDemandInterval = 1, nint_demand
    	do iObservationInterval = 1, nint_obs 
    		do iLink = 1, noofarcs_org
	if (LP_ODDemand(iOrigin, iDestination,iDemandInterval) > 
     +  0.0001 .and. LinkIndex_obs(iLink).gt.0) then
	if(LP_ODFlow(iOrigin,iDestination, iDemandInterval,iLink, 
     +  iObservationInterval) >0.001) then
	LinkProportion = LP_ODFlow(iOrigin,iDestination,iDemandInterval,
     +  iLink,iObservationInterval)/LP_ODDemand(iOrigin,iDestination,
     +  iDemandInterval)
	value1 = LP_ODFlow(iOrigin,iDestination,iDemandInterval,iLink,
     +  iObservationInterval)
	value2 = LP_ODDemand(iOrigin,iDestination,iDemandInterval)
	inonzeronum= inonzeronum+1
	write(901,"(i10,'.', i10,'.', i10,'.', i10,'.',i10,'.',1F25.5)")
     +  iOrigin,iDestination,iDemandInterval,iLink,iObservationInterval,
     +  LinkProportion
			    endif
			endif
		enddo
	    enddo
	enddo
 	enddo
	enddo
	write(901,*) '/;'

	open(file='LPnonzero.dat',unit=915,status='unknown',iostat=error) 
	write(915,*) inonzeronum

	do iOrigin=1,nzones
 	do iDestination=1,nzones
	do iDemandInterval=1,nint_demand
	value2=LP_ODDemand(iOrigin,iDestination,iDemandInterval)
	write(915,*) iOrigin,iDestination,iDemandInterval,value2
	enddo
 	enddo
	enddo

	close(915)

	deallocate(LP_ODDemand,stat=error)
	deallocate(LP_ODFlow,stat=error)
    	deallocate(LinkIndex_obs,stat=error)	
	close(901)

	return
	end
